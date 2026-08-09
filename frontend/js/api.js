/* ===================== API Client ===================== */
const API_BASE = "";

async function apiRequest(method, path, { body, isFormData } = {}) {
    const options = { method, headers: {} };
    if (body) {
        if (isFormData) {
            options.body = body;
        } else {
            options.headers["Content-Type"] = "application/json";
            options.body = JSON.stringify(body);
        }
    }
    const res = await fetch(API_BASE + path, options);
    if (res.status === 401) {
        window.location.href = "/login.html";
        throw new Error("Kirish talab qilinadi");
    }
    let data = null;
    try {
        data = await res.json();
    } catch (e) {
        data = null;
    }
    if (!res.ok) {
        const message = (data && (data.detail || data.message)) || `Xato: HTTP ${res.status}`;
        throw new Error(typeof message === "string" ? message : JSON.stringify(message));
    }
    return data;
}

const api = {
    // Auth
    me: () => apiRequest("GET", "/api/auth/me"),
    logout: () => apiRequest("POST", "/api/auth/logout"),

    // Shorts (= yuklangan videolar)
    getShorts: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return apiRequest("GET", `/api/shorts${qs ? "?" + qs : ""}`);
    },
    getShort: (id) => apiRequest("GET", `/api/shorts/${id}`),
    updateShort: (id, payload) => apiRequest("PATCH", `/api/shorts/${id}`, { body: payload }),
    setSubtitle: (id, payload) => apiRequest("POST", `/api/shorts/${id}/subtitle`, { body: payload }),
    setWatermark: (id, enabled, formData) => apiRequest("POST", `/api/shorts/${id}/watermark?enabled=${enabled}`, { body: formData, isFormData: true }),
    setCropMode: (id, mode) => apiRequest("POST", `/api/shorts/${id}/crop?crop_mode=${mode}`),
    renderShort: (id) => apiRequest("POST", `/api/shorts/${id}/render`),
    mergeShorts: (shortIds, title) => apiRequest("POST", "/api/shorts/merge", { body: { short_ids: shortIds, title } }),
    generateMetadata: (id) => apiRequest("POST", `/api/shorts/${id}/generate-metadata`),
    analyzeShortContent: (id) => apiRequest("POST", `/api/shorts/${id}/analyze`),
    uploadShortNow: (id) => apiRequest("POST", `/api/shorts/${id}/upload-now`),
    uploadManualShort: (formData) => apiRequest("POST", "/api/shorts/upload-manual", { body: formData, isFormData: true }),
    cancelAllScheduled: () => apiRequest("POST", "/api/shorts/cancel-all-scheduled"),
    bulkUpdateMetadata: (shortIds, payload) => apiRequest("POST", "/api/shorts/bulk-metadata", { body: { short_ids: shortIds, ...payload } }),
    deleteShort: (id) => apiRequest("DELETE", `/api/shorts/${id}`),

    // Settings
    getSettings: () => apiRequest("GET", "/api/settings"),
    updateSettings: (settings) => apiRequest("POST", "/api/settings", { body: { settings } }),
    getApiKeys: () => apiRequest("GET", "/api/settings/api-keys"),
    saveApiKey: (provider, apiKey) => apiRequest("POST", "/api/settings/api-keys", { body: { provider, api_key: apiKey } }),
    toggleApiKey: (provider, enabled) => apiRequest("POST", "/api/settings/api-keys/toggle", { body: { provider, enabled } }),
    deleteApiKey: (provider) => apiRequest("DELETE", `/api/settings/api-keys/${provider}`),
    testApiKey: (provider, apiKey) => apiRequest("POST", "/api/settings/api-keys/test", { body: { provider, api_key: apiKey || null } }),

    // YouTube
    uploadClientSecret: (formData) => apiRequest("POST", "/api/youtube/client-secret", { body: formData, isFormData: true }),
    deleteClientSecret: () => apiRequest("DELETE", "/api/youtube/client-secret"),
    getYoutubeAccount: () => apiRequest("GET", "/api/youtube/account"),
    disconnectYoutube: () => apiRequest("POST", "/api/youtube/disconnect"),
    startOAuth: () => apiRequest("GET", "/api/youtube/oauth/start"),
    getPlaylists: () => apiRequest("GET", "/api/youtube/playlists"),
    getCategories: () => apiRequest("GET", "/api/youtube/categories"),

    // Prompts
    getPrompts: () => apiRequest("GET", "/api/prompts"),
    getPrompt: (id) => apiRequest("GET", `/api/prompts/${id}`),
    createPrompt: (payload) => apiRequest("POST", "/api/prompts", { body: payload }),
    updatePrompt: (id, payload) => apiRequest("PATCH", `/api/prompts/${id}`, { body: payload }),
    activatePrompt: (id) => apiRequest("POST", `/api/prompts/${id}/activate`),
    deletePrompt: (id) => apiRequest("DELETE", `/api/prompts/${id}`),

    // Calendar
    getSlots: () => apiRequest("GET", "/api/calendar/slots"),
    addSlot: (hour, minute) => apiRequest("POST", "/api/calendar/slots", { body: { hour, minute } }),
    deleteSlot: (id) => apiRequest("DELETE", `/api/calendar/slots/${id}`),
    toggleSlot: (id, enabled) => apiRequest("PATCH", `/api/calendar/slots/${id}`, { body: { enabled } }),
    getEvents: (start, end) => apiRequest("GET", `/api/calendar/events?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`),
    reschedule: (shortId, newDatetimeLocal) => apiRequest("POST", "/api/calendar/reschedule", { body: { short_id: shortId, new_datetime_local: newDatetimeLocal } }),
    autoSchedule: (dailyCount) => apiRequest("POST", "/api/calendar/auto-schedule", { body: { daily_count: dailyCount || null } }),
    simpleSchedule: (dailyCount, hours) => apiRequest("POST", "/api/calendar/simple-schedule", { body: { daily_count: dailyCount, hours } }),
    intervalSchedule: (intervalHours, startAtLocal) => apiRequest("POST", "/api/calendar/interval-schedule", { body: { interval_hours: intervalHours, start_at_local: startAtLocal || null } }),
    getTimezone: () => apiRequest("GET", "/api/calendar/timezone"),
    setTimezone: (tz) => apiRequest("POST", "/api/calendar/timezone", { body: { timezone: tz } }),

    // Dashboard
    getStats: () => apiRequest("GET", "/api/dashboard/stats"),
    getQueue: () => apiRequest("GET", "/api/dashboard/queue"),
    getTasks: (limit) => apiRequest("GET", `/api/dashboard/tasks?limit=${limit || 100}`),
    getLogs: (limit, level) => apiRequest("GET", `/api/dashboard/logs?limit=${limit || 200}${level ? "&level=" + level : ""}`),
    getUploadHistory: () => apiRequest("GET", "/api/dashboard/upload-history"),
    getFiles: (folder) => apiRequest("GET", `/api/dashboard/files?folder=${folder}`),
    deleteFile: (folder, filename) => apiRequest("DELETE", `/api/dashboard/files/${folder}/${encodeURIComponent(filename)}`),
    getStorageUsage: () => apiRequest("GET", "/api/dashboard/storage-usage"),
    getChannelStats: () => apiRequest("GET", "/api/dashboard/channel-stats"),
    getRecentVideos: (limit) => apiRequest("GET", `/api/dashboard/recent-videos?limit=${limit || 10}`),
};
