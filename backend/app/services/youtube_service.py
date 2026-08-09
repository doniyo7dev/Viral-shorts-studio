"""
YouTube Data API v3 bilan to'liq integratsiya (OAuth, video yuklash, kanal statistikasi).
Har bir foydalanuvchi o'zining alohida YouTube kanaliga ulanadi — barcha funksiyalar
user_id parametri orqali `youtube_account` jadvalidagi tegishli qatorni ishlatadi.
"""
import json
from pathlib import Path

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from ..config import YOUTUBE_SCOPES, YOUTUBE_REDIRECT_URI, CLIENT_SECRETS_DIR
from ..database import get_cursor
from ..utils.crypto import encrypt_text, decrypt_text
from ..utils.logger import log


# ==================== CLIENT SECRET BOSHQARUVI ====================

def save_client_secret(user_id: int, file_bytes: bytes) -> dict:
    try:
        data = json.loads(file_bytes.decode("utf-8"))
        if "installed" not in data and "web" not in data:
            return {"success": False, "message": "Fayl formati noto'g'ri: 'installed' yoki 'web' kaliti topilmadi."}
    except Exception as e:
        return {"success": False, "message": f"JSON fayl noto'g'ri: {e}"}

    path = CLIENT_SECRETS_DIR / f"client_secret_{user_id}.json"
    path.write_bytes(file_bytes)

    with get_cursor(commit=True) as cur:
        cur.execute("SELECT user_id FROM youtube_account WHERE user_id = ?", (user_id,))
        if cur.fetchone():
            cur.execute("UPDATE youtube_account SET client_secret_path = ? WHERE user_id = ?", (str(path), user_id))
        else:
            cur.execute("INSERT INTO youtube_account (user_id, client_secret_path) VALUES (?, ?)", (user_id, str(path)))

    log("YouTube Client Secret fayli saqlandi", "success", "youtube_service", user_id=user_id)
    return {"success": True, "message": "Client Secret muvaffaqiyatli saqlandi."}


def delete_client_secret(user_id: int):
    with get_cursor() as cur:
        cur.execute("SELECT client_secret_path FROM youtube_account WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
    if row and row.get("client_secret_path"):
        Path(row["client_secret_path"]).unlink(missing_ok=True)

    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE youtube_account SET client_secret_path=NULL, encrypted_token_json=NULL, "
            "channel_id=NULL, channel_title=NULL, channel_thumbnail=NULL, connected_at=NULL WHERE user_id = ?",
            (user_id,),
        )
    log("YouTube Client Secret o'chirildi", "info", "youtube_service", user_id=user_id)


def get_client_secret_path(user_id: int) -> str:
    with get_cursor() as cur:
        cur.execute("SELECT client_secret_path FROM youtube_account WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
    return row["client_secret_path"] if row and row.get("client_secret_path") else ""


# ==================== OAUTH FLOW ====================

def get_authorization_url(user_id: int) -> dict:
    secret_path = get_client_secret_path(user_id)
    if not secret_path or not Path(secret_path).exists():
        return {"success": False, "message": "Avval Client Secret faylini yuklang."}

    flow = Flow.from_client_secrets_file(
        secret_path, scopes=YOUTUBE_SCOPES, redirect_uri=YOUTUBE_REDIRECT_URI
    )
    auth_url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    # 'state' orqali qaysi foydalanuvchi OAuth boshlaganini eslab qolamiz (callback'da
    # kerak bo'ladi, chunki Google redirect URI foydalanuvchi haqida ma'lumot bermaydi).
    # Har bir foydalanuvchi o'zining shaxsiy 'oauth_state' yozuvida saqlanadi — bir nechta
    # kishi bir vaqtda ulanishni boshlasa ham bir-birining state'ini ustidan yozmaydi.
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO settings (user_id, `key`, value) VALUES (?, 'oauth_state', ?) "
            "ON DUPLICATE KEY UPDATE value = VALUES(value)",
            (user_id, state),
        )
    return {"success": True, "auth_url": auth_url}


def _resolve_oauth_owner(state: str) -> int:
    """OAuth callback'da 'state' orqali qaysi foydalanuvchi ulanmoqchi bo'lganini topadi."""
    if not state:
        return None
    with get_cursor() as cur:
        cur.execute(
            "SELECT user_id FROM settings WHERE `key` = 'oauth_state' AND value = ? LIMIT 1", (state,)
        )
        row = cur.fetchone()
    return row["user_id"] if row else None


def handle_oauth_callback(code: str, state: str) -> dict:
    user_id = _resolve_oauth_owner(state)
    if user_id is None:
        return {"success": False, "message": "Sessiya eskirgan yoki noto'g'ri. Qaytadan urinib ko'ring."}

    secret_path = get_client_secret_path(user_id)
    if not secret_path or not Path(secret_path).exists():
        return {"success": False, "message": "Client Secret fayli topilmadi."}

    try:
        flow = Flow.from_client_secrets_file(
            secret_path, scopes=YOUTUBE_SCOPES, redirect_uri=YOUTUBE_REDIRECT_URI
        )
        flow.fetch_token(code=code)
        creds = flow.credentials

        token_data = {
            "token": creds.token, "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri, "client_id": creds.client_id,
            "client_secret": creds.client_secret, "scopes": creds.scopes,
        }

        youtube = build("youtube", "v3", credentials=creds)
        channel_resp = youtube.channels().list(part="snippet", mine=True).execute()
        channel = channel_resp["items"][0] if channel_resp.get("items") else {}
        channel_id = channel.get("id", "")
        channel_title = channel.get("snippet", {}).get("title", "")
        channel_thumb = channel.get("snippet", {}).get("thumbnails", {}).get("default", {}).get("url", "")

        encrypted_token = encrypt_text(json.dumps(token_data))

        with get_cursor(commit=True) as cur:
            cur.execute("SELECT user_id FROM youtube_account WHERE user_id = ?", (user_id,))
            if cur.fetchone():
                cur.execute(
                    "UPDATE youtube_account SET encrypted_token_json=?, channel_id=?, channel_title=?, "
                    "channel_thumbnail=?, connected_at=NOW() WHERE user_id = ?",
                    (encrypted_token, channel_id, channel_title, channel_thumb, user_id),
                )
            else:
                cur.execute(
                    "INSERT INTO youtube_account (user_id, encrypted_token_json, channel_id, channel_title, "
                    "channel_thumbnail, connected_at) VALUES (?, ?, ?, ?, ?, NOW())",
                    (user_id, encrypted_token, channel_id, channel_title, channel_thumb),
                )

        log(f"YouTube akkaunt ulandi: {channel_title}", "success", "youtube_service", user_id=user_id)
        return {"success": True, "channel_title": channel_title}
    except Exception as e:
        log(f"OAuth callback xatosi: {e}", "error", "youtube_service", user_id=user_id)
        return {"success": False, "message": str(e)}


def get_connected_account(user_id: int) -> dict:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM youtube_account WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
    if not row or not row.get("encrypted_token_json"):
        return {"connected": False, "has_client_secret": bool(row and row.get("client_secret_path"))}
    return {
        "connected": True,
        "channel_id": row.get("channel_id"),
        "channel_title": row.get("channel_title"),
        "channel_thumbnail": row.get("channel_thumbnail"),
        "connected_at": str(row.get("connected_at")) if row.get("connected_at") else None,
        "has_client_secret": bool(row.get("client_secret_path")),
    }


def disconnect_account(user_id: int):
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE youtube_account SET encrypted_token_json=NULL, channel_id=NULL, channel_title=NULL, "
            "channel_thumbnail=NULL, connected_at=NULL WHERE user_id = ?",
            (user_id,),
        )
    log("YouTube akkaunt uzildi", "info", "youtube_service", user_id=user_id)


def _get_credentials(user_id: int) -> Credentials:
    with get_cursor() as cur:
        cur.execute("SELECT encrypted_token_json FROM youtube_account WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
    if not row or not row.get("encrypted_token_json"):
        raise RuntimeError("YouTube akkaunt ulanmagan.")

    token_data = json.loads(decrypt_text(row["encrypted_token_json"]))
    creds = Credentials(
        token=token_data["token"], refresh_token=token_data["refresh_token"],
        token_uri=token_data["token_uri"], client_id=token_data["client_id"],
        client_secret=token_data["client_secret"], scopes=token_data["scopes"],
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        new_token_data = {
            "token": creds.token, "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri, "client_id": creds.client_id,
            "client_secret": creds.client_secret, "scopes": creds.scopes,
        }
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE youtube_account SET encrypted_token_json = ? WHERE user_id = ?",
                (encrypt_text(json.dumps(new_token_data)), user_id),
            )
    return creds


def get_my_playlists(user_id: int) -> list:
    try:
        creds = _get_credentials(user_id)
        youtube = build("youtube", "v3", credentials=creds)
        resp = youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute()
        return [{"id": p["id"], "title": p["snippet"]["title"]} for p in resp.get("items", [])]
    except Exception as e:
        log(f"Playlist ro'yxatini olishda xato: {e}", "error", "youtube_service", user_id=user_id)
        return []


def get_channel_statistics(user_id: int) -> dict:
    """Kanalning real-time statistikasi: obunachilar, umumiy ko'rishlar, video soni."""
    try:
        creds = _get_credentials(user_id)
        youtube = build("youtube", "v3", credentials=creds)
        resp = youtube.channels().list(part="snippet,statistics", mine=True).execute()
        items = resp.get("items", [])
        if not items:
            return {"connected": False}
        channel = items[0]
        stats = channel.get("statistics", {})
        snippet = channel.get("snippet", {})
        return {
            "connected": True,
            "channel_title": snippet.get("title", ""),
            "channel_thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
            "subscriber_count": int(stats.get("subscriberCount", 0)),
            "view_count": int(stats.get("viewCount", 0)),
            "video_count": int(stats.get("videoCount", 0)),
            "hidden_subscriber_count": stats.get("hiddenSubscriberCount", False),
        }
    except RuntimeError:
        return {"connected": False}
    except Exception as e:
        log(f"Kanal statistikasini olishda xato: {e}", "error", "youtube_service", user_id=user_id)
        return {"connected": False, "error": str(e)}


def get_recent_video_statistics(user_id: int, max_results: int = 10) -> list:
    """Kanalning so'nggi videolari uchun ko'rishlar/layk/izoh statistikasini to'g'ridan-to'g'ri YouTube'dan oladi."""
    try:
        creds = _get_credentials(user_id)
        youtube = build("youtube", "v3", credentials=creds)

        channel_resp = youtube.channels().list(part="contentDetails", mine=True).execute()
        items = channel_resp.get("items", [])
        if not items:
            return []
        uploads_playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

        playlist_resp = youtube.playlistItems().list(
            part="contentDetails", playlistId=uploads_playlist_id, maxResults=max_results
        ).execute()
        video_ids = [i["contentDetails"]["videoId"] for i in playlist_resp.get("items", [])]
        if not video_ids:
            return []

        videos_resp = youtube.videos().list(part="snippet,statistics", id=",".join(video_ids)).execute()

        results = []
        for v in videos_resp.get("items", []):
            stats = v.get("statistics", {})
            results.append({
                "video_id": v["id"],
                "title": v.get("snippet", {}).get("title", ""),
                "thumbnail": v.get("snippet", {}).get("thumbnails", {}).get("default", {}).get("url", ""),
                "published_at": v.get("snippet", {}).get("publishedAt", ""),
                "view_count": int(stats.get("viewCount", 0)),
                "like_count": int(stats.get("likeCount", 0)),
                "comment_count": int(stats.get("commentCount", 0)),
                "url": f"https://www.youtube.com/watch?v={v['id']}",
            })
        return results
    except RuntimeError:
        return []
    except Exception as e:
        log(f"Video statistikasini olishda xato: {e}", "error", "youtube_service", user_id=user_id)
        return []


def upload_video(
    user_id: int, short_id: int, file_path: str, title: str, description: str, tags: list,
    category_id: str = "22", visibility: str = "private", made_for_kids: bool = False,
    playlist_id: str = None, thumbnail_path: str = None, publish_at: str = None,
    progress_callback=None,
) -> dict:
    try:
        creds = _get_credentials(user_id)
        youtube = build("youtube", "v3", credentials=creds)

        status_body = {"privacyStatus": visibility, "selfDeclaredMadeForKids": made_for_kids}
        if publish_at:
            status_body["privacyStatus"] = "private"
            status_body["publishAt"] = publish_at

        body = {
            "snippet": {"title": title[:100], "description": description[:5000],
                        "tags": tags[:500], "categoryId": category_id},
            "status": status_body,
        }

        media = MediaFileUpload(file_path, chunksize=1024 * 1024 * 4, resumable=True, mimetype="video/*")
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status and progress_callback:
                progress_callback(int(status.progress() * 100))

        video_id = response["id"]
        video_url = f"https://www.youtube.com/watch?v={video_id}"

        if thumbnail_path and Path(thumbnail_path).exists():
            try:
                youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumbnail_path)).execute()
            except HttpError as e:
                log(f"Thumbnail o'rnatishda xato: {e}", "warning", "youtube_service", user_id=user_id)

        if playlist_id:
            try:
                youtube.playlistItems().insert(
                    part="snippet",
                    body={"snippet": {"playlistId": playlist_id,
                                       "resourceId": {"kind": "youtube#video", "videoId": video_id}}},
                ).execute()
            except HttpError as e:
                log(f"Playlistga qo'shishda xato: {e}", "warning", "youtube_service", user_id=user_id)

        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE shorts SET youtube_video_id=?, youtube_url=?, status='uploaded', uploaded_at=NOW() WHERE id=?",
                (video_id, video_url, short_id),
            )

        log(f"Short #{short_id} YouTube'ga yuklandi: {video_url}", "success", "youtube_service", user_id=user_id)
        return {"success": True, "video_id": video_id, "video_url": video_url}

    except Exception as e:
        error_msg = str(e)
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE shorts SET status='failed', error_message=? WHERE id=?", (error_msg, short_id)
            )
        log(f"Short #{short_id} yuklashda xato: {error_msg}", "error", "youtube_service", user_id=user_id)
        return {"success": False, "message": error_msg}


YOUTUBE_CATEGORIES = {
    "1": "Film & Animation", "2": "Autos & Vehicles", "10": "Music",
    "15": "Pets & Animals", "17": "Sports", "19": "Travel & Events",
    "20": "Gaming", "22": "People & Blogs", "23": "Comedy",
    "24": "Entertainment", "25": "News & Politics", "26": "Howto & Style",
    "27": "Education", "28": "Science & Technology",
}
