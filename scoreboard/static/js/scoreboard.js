/**
 * KoTH CTF — Live Scoreboard
 * Real-time scoreboard with WebSocket updates
 */

const API_BASE = window.location.origin + '/api';
const WS_URL = (window.location.protocol === 'https:' ? 'wss://' : 'ws://') +
    window.location.host + '/ws/scoreboard';

let ws = null;
let wsReconnectTimer = null;
let scoreboardData = null;
let activeCategory = 'all';
let gameElapsed = 0;
let gameDuration = 21600; // 6 hours
let gameRunning = false;
let timerInterval = null;

// ─── Initialization ─────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    fetchScoreboard();
    fetchFirstBloods();
    connectWebSocket();

    // Refresh data every 10 seconds as fallback
    setInterval(fetchScoreboard, 10000);
    setInterval(fetchFirstBloods, 30000);
});

// ─── API Calls ──────────────────────────────────────────────────────────────

async function fetchScoreboard() {
    try {
        const res = await fetch(`${API_BASE}/scoreboard`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        scoreboardData = await res.json();
        renderScoreboard(scoreboardData);
    } catch (e) {
        console.error('Failed to fetch scoreboard:', e);
    }
}

async function fetchFirstBloods() {
    try {
        const res = await fetch(`${API_BASE}/scoreboard/first-bloods`);
        if (!res.ok) return;
        const data = await res.json();
        renderFirstBloods(data);
    } catch (e) {
        console.error('Failed to fetch first bloods:', e);
    }
}

// ─── WebSocket ──────────────────────────────────────────────────────────────

function connectWebSocket() {
    if (ws && ws.readyState <= 1) return;

    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        console.log('WebSocket connected');
        updateWSStatus(true);
        addEvent('system', 'Terhubung ke server');

        // Ping every 30s
        setInterval(() => {
            if (ws && ws.readyState === 1) ws.send('ping');
        }, 30000);
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'pong') return;
            handleWSMessage(msg);
        } catch (e) {
            console.error('WS parse error:', e);
        }
    };

    ws.onclose = () => {
        updateWSStatus(false);
        addEvent('system', 'Koneksi terputus, mencoba koneksi ulang...');
        scheduleReconnect();
    };

    ws.onerror = (err) => {
        console.error('WebSocket error:', err);
        updateWSStatus(false);
    };
}

function scheduleReconnect() {
    if (wsReconnectTimer) clearTimeout(wsReconnectTimer);
    wsReconnectTimer = setTimeout(connectWebSocket, 3000);
}

function updateWSStatus(connected) {
    // ws-status indicator removed from UI — no-op
}

function handleWSMessage(msg) {
    switch (msg.type) {
        case 'tick_update':
            fetchScoreboard(); // Refresh on every tick
            addEvent('tick_update', `Tick #${msg.data.tick_number} selesai`);
            break;

        case 'king_change':
            const kc = msg.data;
            addEvent('king_change',
                `👑 ${kc.new_king_name || '???'} merebut ${kc.hill_name}!`);
            showToast('king_change',
                `👑 King Change! ${kc.new_king_name} menguasai ${kc.hill_name}`);
            fetchScoreboard();
            break;

        case 'first_blood':
            const fb = msg.data;
            addEvent('first_blood',
                `🩸 FIRST BLOOD! ${fb.team_name} pada ${fb.hill_name} (+${fb.bonus})`);
            showToast('first_blood',
                `🩸 First Blood! ${fb.team_name} → ${fb.hill_name} (+${fb.bonus}pts)`);
            fetchFirstBloods();
            fetchScoreboard();
            break;

        case 'game_event':
            const ge = msg.data;
            addEvent('game_event', `⚡ ${ge.event.toUpperCase()}`);
            showToast('game_event', `⚡ Game: ${ge.event}`);
            fetchScoreboard();
            break;

        default:
            console.log('Unknown WS message:', msg);
    }
}

// ─── Render Functions ───────────────────────────────────────────────────────

function renderScoreboard(data) {
    renderHills(data.hills);
    renderLeaderboard(data.teams);
    updateGameStatus(data);
}

function renderHills(hills) {
    const grid = document.getElementById('hills-grid');
    grid.innerHTML = hills.map(hill => {
        const hasCaptured = !!hill.current_king;
        const cardClass = hasCaptured ? 'captured' : 'uncaptured';

        return `
            <div class="hill-card ${cardClass}">
                <div class="hill-name">${escHtml(hill.hill_name)}</div>
                <div class="hill-meta">
                    ${hill.is_behind_pivot ? '🔒 Behind Pivot' : '🌐 Direct Access'}
                </div>
                <div class="hill-king">
                    ${hasCaptured
                        ? `<span class="king-crown">👑</span>
                           <span class="king-name">${escHtml(hill.current_king)}</span>`
                        : `<span class="king-none">Belum dikuasai</span>`
                    }
                </div>
                <div class="hill-badges">
                    <span class="badge multiplier">×${hill.multiplier}</span>
                    ${hill.is_behind_pivot ? '<span class="badge pivot">PIVOT</span>' : ''}
                    <span class="badge ${hill.sla_status ? 'sla-up' : 'sla-down'}">
                        SLA ${hill.sla_status ? 'UP' : 'DOWN'}
                    </span>
                </div>
            </div>
        `;
    }).join('');
}

function renderLeaderboard(teams) {
    const tbody = document.getElementById('leaderboard-body');

    let filtered = teams;
    if (activeCategory !== 'all') {
        filtered = teams.filter(t => t.category === activeCategory);
    }

    // Re-rank after filter
    filtered = filtered.map((t, i) => ({ ...t, rank: i + 1 }));

    tbody.innerHTML = filtered.map(team => {
        const rankClass = team.rank <= 3 ? `rank-${team.rank}` : 'rank-other';
        const catClass = team.category || 'default';

        return `
            <tr>
                <td class="col-rank">
                    <span class="rank-badge ${rankClass}">${team.rank}</span>
                </td>
                <td class="col-team">
                    <div class="team-name">${escHtml(team.team_name)}</div>
                    ${team.display_name && team.display_name !== team.team_name
                        ? `<div class="team-display-name">${escHtml(team.display_name)}</div>`
                        : ''}
                </td>
                <td class="col-cat">
                    <span class="category-badge ${catClass}">
                        ${(catClass || 'default').toUpperCase()}
                    </span>
                </td>
                <td class="col-points">
                    <span class="points-highlight">${team.total_points.toLocaleString()}</span>
                </td>
                <td class="col-hills">${team.hills_owned}</td>
                <td class="col-ticks">${team.total_ticks_as_king}</td>
                <td class="col-fb">${team.first_bloods}</td>
            </tr>
        `;
    }).join('');
}

function renderFirstBloods(fbList) {
    const grid = document.getElementById('first-bloods-grid');

    if (!fbList || fbList.length === 0) {
        grid.innerHTML = `
            <div class="fb-card empty">
                <div class="fb-icon">🩸</div>
                <div>Belum ada first blood</div>
            </div>
        `;
        return;
    }

    grid.innerHTML = fbList.map(fb => `
        <div class="fb-card">
            <div class="fb-icon">🩸</div>
            <div class="fb-hill">${escHtml(fb.hill_name)}</div>
            <div class="fb-team">${escHtml(fb.team_name)}</div>
            <div class="fb-bonus">+${fb.bonus_points} pts</div>
            <div class="fb-tick">Tick #${fb.tick_number}</div>
        </div>
    `).join('');
}

function updateGameStatus(data) {
    const tick = document.getElementById('tick-display');
    tick.textContent = `#${data.current_tick}`;

    const wasRunning = gameRunning;
    gameRunning = data.game_status === 'running';

    // Sync remaining time from server on every fetch
    if (data.remaining_seconds !== undefined) {
        gameRemaining = data.remaining_seconds;
    }
    if (data.elapsed_seconds !== undefined) {
        gameElapsed = data.elapsed_seconds;
    }

    // Update game status badge in header
    const timerEl = document.getElementById('game-timer');
    if (timerEl) {
        if (data.game_status === 'running') {
            timerEl.classList.add('running');
            timerEl.classList.remove('paused', 'stopped');
        } else if (data.game_status === 'paused') {
            timerEl.classList.add('paused');
            timerEl.classList.remove('running', 'stopped');
        } else {
            timerEl.classList.add('stopped');
            timerEl.classList.remove('running', 'paused');
        }
    }

    // Start/stop countdown timer
    if (gameRunning && !timerInterval) {
        startTimer();
    } else if (!gameRunning && timerInterval) {
        clearInterval(timerInterval);
        timerInterval = null;
    }

    // Always update display with latest server values
    updateTimerDisplay();

    // Show --:--:-- for not_started and finished
    if (data.game_status === 'finished' || data.game_status === 'not_started') {
        const timerValEl = document.getElementById('timer-display');
        if (timerValEl) {
            timerValEl.textContent = '--:--:--';
        }
    }
}

// ─── Timer ──────────────────────────────────────────────────────────────────

let gameRemaining = 0;

function startTimer() {
    updateTimerDisplay();
    timerInterval = setInterval(() => {
        if (gameRemaining > 0) {
            gameRemaining--;
            gameElapsed++;
        }
        updateTimerDisplay();
    }, 1000);
}

function updateTimerDisplay() {
    // Show --:--:-- when game is not running
    if (!gameRunning) {
        document.getElementById('timer-display').textContent = '--:--:--';
        return;
    }
    const remaining = Math.max(0, gameRemaining);
    const h = Math.floor(remaining / 3600);
    const m = Math.floor((remaining % 3600) / 60);
    const s = remaining % 60;
    document.getElementById('timer-display').textContent =
        `${pad(h)}:${pad(m)}:${pad(s)}`;
}

function pad(n) {
    return n.toString().padStart(2, '0');
}

// ─── Events ─────────────────────────────────────────────────────────────────

function addEvent(type, text) {
    const feed = document.getElementById('event-feed');
    // Use WIB (UTC+7) for event timestamps
    const now = new Date();
    const wib = new Date(now.getTime() + (7 * 60 - now.getTimezoneOffset()) * 60000);
    const time = `${pad(wib.getHours())}:${pad(wib.getMinutes())}:${pad(wib.getSeconds())}`;

    const item = document.createElement('div');
    item.className = `event-item ${type} new`;
    item.innerHTML = `
        <span class="event-time">${time}</span>
        <span class="event-text">${escHtml(text)}</span>
    `;

    feed.insertBefore(item, feed.firstChild);

    // Keep max 100 events
    while (feed.children.length > 100) {
        feed.removeChild(feed.lastChild);
    }

    // Remove animation class after it plays
    setTimeout(() => item.classList.remove('new'), 300);
}

// ─── Toasts ─────────────────────────────────────────────────────────────────

function showToast(type, message) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'toastOut 0.3s ease-in forwards';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ─── Category Filter ────────────────────────────────────────────────────────

function filterCategory(cat) {
    activeCategory = cat;
    document.querySelectorAll('.tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.category === cat);
    });
    if (scoreboardData) {
        renderLeaderboard(scoreboardData.teams);
    }
}

// ─── Utility ────────────────────────────────────────────────────────────────

function escHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
