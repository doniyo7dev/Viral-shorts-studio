/* ===================== Umumiy Utility va Layout ===================== */

const NAV_LINKS = [
    { name: "Dashboard", path: "index.html", icon: "layout-dashboard" },
    { name: "Videolarim", path: "projects.html", icon: "film" },
    { name: "Statistika", path: "statistics.html", icon: "bar-chart-3" },
    { name: "Calendar", path: "calendar.html", icon: "calendar" },
    { name: "Prompts", path: "prompts.html", icon: "sparkles" },
    { name: "Settings", path: "settings.html", icon: "settings" },
];

function currentPageName() {
    const path = window.location.pathname.split("/").pop() || "index.html";
    return path === "" ? "index.html" : path;
}

function renderLayout(activePage) {
    const current = activePage || currentPageName();

    document.getElementById("ambient-bg").innerHTML = `
        <div class="ambient-orb-purple"></div>
        <div class="ambient-orb-blue"></div>
    `;

    const sidebarLinks = NAV_LINKS.map(link => `
        <a href="${link.path}" class="sidebar-link ${current === link.path ? "active" : ""}">
            <i data-lucide="${link.icon}" style="width:20px;height:20px;"></i>
            <span>${link.name}</span>
        </a>
    `).join("");

    document.getElementById("sidebar").innerHTML = `
        <div class="flex items-center gap-3 px-2 py-4 mb-6">
            <div class="w-8 h-8 rounded-lg bg-gradient-to-tr from-purple-500 to-pink-500 flex items-center justify-center">
                <i data-lucide="sparkles" style="width:18px;height:18px;color:white;"></i>
            </div>
            <h1 class="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-gray-400">
                Viral Shorts
            </h1>
        </div>
        <nav class="flex-1 space-y-2">${sidebarLinks}</nav>
        <div id="sidebar-user" class="px-2 py-3 border-t border-white/10 mt-2"></div>
    `;

    const bottomLinks = NAV_LINKS.map(link => `
        <a href="${link.path}" class="bottom-nav-link ${current === link.path ? "active" : ""}">
            <i data-lucide="${link.icon}" style="width:20px;height:20px;"></i>
            <span>${link.name}</span>
        </a>
    `).join("");
    document.getElementById("bottom-nav").innerHTML = bottomLinks;

    if (window.lucide) lucide.createIcons();
    renderCurrentUser();
}

async function renderCurrentUser() {
    const container = document.getElementById("sidebar-user");
    if (!container) return;
    try {
        const user = await api.me();
        container.innerHTML = `
            <div class="flex items-center justify-between gap-2">
                <div class="flex items-center gap-2 min-w-0">
                    <div class="w-7 h-7 rounded-full bg-gradient-to-tr from-purple-500 to-pink-500 flex items-center justify-center text-xs font-bold flex-shrink-0">
                        ${escapeHtml(user.name.trim().charAt(0).toUpperCase())}
                    </div>
                    <span class="text-sm text-gray-300 truncate">${escapeHtml(user.name)}</span>
                </div>
                <button onclick="logoutUser()" class="text-gray-500 hover:text-red-400 transition flex-shrink-0" title="Chiqish">
                    <i data-lucide="log-out" style="width:16px;height:16px;"></i>
                </button>
            </div>
        `;
        if (window.lucide) lucide.createIcons();
    } catch (e) {
        // apiRequest allaqachon 401'da login.html'ga yo'naltiradi
    }
}

async function logoutUser() {
    try {
        await api.logout();
    } catch (e) {
        // baribir login sahifasiga yo'naltiramiz
    }
    window.location.href = "/login.html";
}

/* ---------------- Toast ---------------- */
function showToast(message, type = "info") {
    let container = document.getElementById("toast-container");
    if (!container) {
        container = document.createElement("div");
        container.id = "toast-container";
        document.body.appendChild(container);
    }
    const icons = { success: "check-circle-2", error: "alert-circle", info: "info" };
    const toast = document.createElement("div");
    toast.className = `toast toast-${type} flex items-center gap-2`;
    toast.innerHTML = `<i data-lucide="${icons[type] || "info"}" style="width:16px;height:16px;flex-shrink:0;"></i><span class="text-sm">${escapeHtml(message)}</span>`;
    container.appendChild(toast);
    if (window.lucide) lucide.createIcons();
    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateY(-10px)";
        toast.style.transition = "all 0.25s ease";
        setTimeout(() => toast.remove(), 250);
    }, 4000);
}

function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    const div = document.createElement("div");
    div.textContent = String(str);
    return div.innerHTML;
}

/* ---------------- Formatlash helperlari ---------------- */
function formatDuration(seconds) {
    if (!seconds && seconds !== 0) return "-";
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
}

function formatFileSize(bytes) {
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let size = bytes;
    let i = 0;
    while (size >= 1024 && i < units.length - 1) {
        size /= 1024;
        i++;
    }
    return `${size.toFixed(1)} ${units[i]}`;
}

function formatDate(isoString) {
    if (!isoString) return "-";
    const d = new Date(isoString.includes("Z") || isoString.includes("+") ? isoString : isoString + "Z");
    return d.toLocaleDateString("uz-UZ", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function formatDateTime(isoString) {
    if (!isoString) return "-";
    const d = new Date(isoString.includes("Z") || isoString.includes("+") ? isoString : isoString + "Z");
    return d.toLocaleString("uz-UZ", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

const STATUS_LABELS = {
    draft: "Draft", scheduled: "Scheduled", processing: "Processing",
    uploading: "Uploading", uploaded: "Uploaded", failed: "Failed",
    analyzing: "Analyzing", uploaded_video: "Uploaded", completed: "Completed",
};

function statusBadge(status) {
    const label = STATUS_LABELS[status] || status;
    return `<span class="badge badge-${status}">${label}</span>`;
}

/* ---------------- Modal helper ---------------- */
function openModal(contentHtml) {
    closeModal();
    const backdrop = document.createElement("div");
    backdrop.id = "app-modal-backdrop";
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `<div class="modal-panel">${contentHtml}</div>`;
    backdrop.addEventListener("click", (e) => {
        if (e.target === backdrop) closeModal();
    });
    document.body.appendChild(backdrop);
    if (window.lucide) lucide.createIcons();
}

function closeModal() {
    const existing = document.getElementById("app-modal-backdrop");
    if (existing) existing.remove();
}

/* ---------------- Loading spinner inline ---------------- */
function loadingSpinner(text = "Yuklanmoqda...") {
    return `<div class="flex flex-col items-center justify-center py-16 text-gray-500">
        <div class="w-8 h-8 border-2 border-purple-500 border-t-transparent rounded-full animate-spin mb-3"></div>
        <p class="text-sm">${escapeHtml(text)}</p>
    </div>`;
}

function emptyState(icon, title, subtitle, actionHtml = "") {
    return `<div class="flex-1 rounded-2xl glass-card p-8 flex flex-col items-center justify-center text-center min-h-[300px]">
        <div class="w-16 h-16 rounded-full bg-white/5 flex items-center justify-center mb-5">
            <i data-lucide="${icon}" style="width:32px;height:32px;color:#9ca3af;"></i>
        </div>
        <h3 class="text-lg font-semibold mb-2">${escapeHtml(title)}</h3>
        <p class="text-gray-400 max-w-md mb-6 text-sm">${escapeHtml(subtitle)}</p>
        ${actionHtml}
    </div>`;
}

document.addEventListener("DOMContentLoaded", () => {
    renderLayout();
});
