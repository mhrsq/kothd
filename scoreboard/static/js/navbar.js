/* ══════════════════════════════════════════════════
   KoTH CTF — Global Navbar Component
   Include via <script src="/static/js/navbar.js"></script>
   ══════════════════════════════════════════════════ */
(function() {
    const role = sessionStorage.getItem('koth_role') || localStorage.getItem('koth_role');
    const teamData = role === 'team' ? JSON.parse(sessionStorage.getItem('koth_team') || localStorage.getItem('koth_team') || '{}') : null;
    const currentPage = location.pathname;

    function isActive(path) {
        return currentPage === path ? 'gn-active' : '';
    }

    // Build nav items based on context
    let navItems = '';

    if (role === 'team') {
        // Team members get full navigation matching the dashboard
        navItems += `<a href="/dashboard" class="gn-link ${isActive('/dashboard')}">🏠 Home</a>`;
        navItems += `<a href="/vpn" class="gn-link ${isActive('/vpn')}">🔐 VPN</a>`;
        navItems += `<a href="/topology" class="gn-link ${isActive('/topology')}">🗺️ Topology</a>`;
        navItems += `<a href="/rules" class="gn-link ${isActive('/rules')}">📜 Rules</a>`;
        navItems += `<a href="/scoreboard" class="gn-link ${isActive('/scoreboard')}">📊 Scoreboard</a>`;
        navItems += `<a href="/history" class="gn-link ${isActive('/history')}">📈 History</a>`;
    } else if (role === 'admin') {
        navItems += `<a href="/scoreboard" class="gn-link ${isActive('/scoreboard')}">📊 Scoreboard</a>`;
        navItems += `<a href="/history" class="gn-link ${isActive('/history')}">📈 History</a>`;
        navItems += `<a href="/organizer" class="gn-link ${isActive('/organizer') || isActive('/admin') ? 'gn-active' : ''}">🎖️ Console Admin</a>`;
    } else {
        // Public / unauthenticated
        navItems += `<a href="/scoreboard" class="gn-link ${isActive('/scoreboard')}">📊 Scoreboard</a>`;
        navItems += `<a href="/history" class="gn-link ${isActive('/history')}">📈 History</a>`;
        navItems += `<a href="/register" class="gn-link ${isActive('/register')}">📝 Register</a>`;
    }

    // Right side — auth section
    let authSection = '';
    if (role === 'team' && teamData) {
        const cat = (teamData.category || 'default').toUpperCase();
        const catCls = 'gn-cat-team';
        authSection = `
            <span class="gn-badge ${catCls}">${cat}</span>
            <span class="gn-team">${escHtml(teamData.display_name || teamData.team_name)}</span>
            <button class="gn-logout" onclick="globalNavLogout()">Logout</button>
        `;
    } else if (role === 'admin') {
        authSection = `
            <span class="gn-badge gn-cat-admin">ADMIN</span>
            <button class="gn-logout" onclick="globalNavLogout()">Logout</button>
        `;
    } else {
        authSection = `<a href="/login" class="gn-login-btn">🔐 Login</a>`;
    }

    // Theme toggle
    const savedTheme = localStorage.getItem('koth_theme') || 'dark';
    if (savedTheme === 'light') document.documentElement.setAttribute('data-theme', 'light');
    const themeIcon = savedTheme === 'light' ? '🌙' : '☀️';
    const themeBtn = `<button class="gn-theme-toggle" onclick="toggleKothTheme()" title="Toggle theme">${themeIcon}</button>`;

    // Build navbar HTML
    const navHtml = `
    <nav class="global-nav" id="globalNav">
        <div class="gn-left">
            <a href="${role === 'team' ? '/dashboard' : role === 'admin' ? '/organizer' : '/scoreboard'}" class="gn-brand">
                <span class="gn-logo">⚔️</span>
                <span class="gn-title">KoTH CTF</span>
            </a>
        </div>
        <div class="gn-center">${navItems}</div>
        <div class="gn-right">${themeBtn}<div class="gn-bell-wrap" style="position:relative;"><button class="gn-bell" onclick="toggleKothBell()" title="Announcements">🔔<span class="gn-bell-badge" id="gnBellBadge" style="display:none;">0</span></button><div class="gn-bell-dropdown" id="gnBellDropdown" style="display:none;"></div></div>${authSection}</div>
        <button class="gn-hamburger" onclick="toggleMobileNav()">☰</button>
    </nav>
    <div class="gn-mobile-menu" id="gnMobileMenu" style="display:none;">
        ${navItems}
        <div style="border-top:1px solid #2a3a4e;margin:8px 0;"></div>
        ${role ? `<button class="gn-logout" style="width:100%;margin:4px 12px;" onclick="globalNavLogout()">🚪 Logout</button>` : `<a href="/login" class="gn-link">🔐 Login</a>`}
    </div>`;

    // Inject CSS
    const style = document.createElement('style');
    style.textContent = `
        .global-nav{display:flex;align-items:center;justify-content:space-between;padding:0 20px;height:56px;background:linear-gradient(135deg,#111827,#1e293b);border-bottom:2px solid #22c55e;position:sticky;top:0;z-index:9999;font-family:'Inter',sans-serif;}
        .gn-left{display:flex;align-items:center;}
        .gn-brand{display:flex;align-items:center;gap:10px;text-decoration:none;color:#e2e8f0;}
        .gn-logo{font-size:24px;filter:drop-shadow(0 0 6px rgba(34,197,94,.4));}
        .gn-title{font-size:14px;font-weight:900;background:linear-gradient(135deg,#22c55e,#06b6d4);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
        .gn-center{display:flex;align-items:center;gap:2px;}
        .gn-link{color:#94a3b8;text-decoration:none;font-size:12px;font-weight:700;padding:8px 12px;border-radius:6px;transition:all .15s;white-space:nowrap;}
        .gn-link:hover,.gn-link.gn-active{background:#243044;color:#06b6d4;}
        .gn-right{display:flex;align-items:center;gap:10px;}
        .gn-team{font-size:12px;font-weight:700;color:#22c55e;background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.25);padding:4px 12px;border-radius:6px;}
        .gn-badge{font-size:10px;font-weight:700;padding:3px 10px;border-radius:12px;}
        .gn-cat-team{background:rgba(59,130,246,.15);color:#3b82f6;}
        .gn-cat-default{background:rgba(249,115,22,.15);color:#f97316;}
        .gn-cat-admin{background:rgba(168,85,247,.15);color:#a855f7;}
        .gn-logout{background:none;border:1px solid #2a3a4e;color:#64748b;padding:5px 12px;border-radius:6px;cursor:pointer;font-size:11px;font-weight:700;font-family:'Inter',sans-serif;transition:all .15s;}
        .gn-logout:hover{border-color:#ef4444;color:#ef4444;}
        .gn-login-btn{color:#06b6d4;text-decoration:none;font-size:12px;font-weight:700;padding:6px 14px;border:1px solid rgba(6,182,212,.3);border-radius:6px;transition:all .15s;}
        .gn-login-btn:hover{background:rgba(6,182,212,.1);}
        .gn-hamburger{display:none;background:none;border:none;color:#e2e8f0;font-size:24px;cursor:pointer;padding:4px 8px;}
        .gn-mobile-menu{background:#111827;border-bottom:1px solid #2a3a4e;padding:8px 12px;position:sticky;top:56px;z-index:9998;}
        .gn-mobile-menu .gn-link{display:block;padding:10px 12px;}
        .gn-theme-toggle{background:none;border:1px solid #2a3a4e;color:#e2e8f0;width:32px;height:32px;border-radius:6px;cursor:pointer;font-size:16px;display:flex;align-items:center;justify-content:center;transition:all .15s;}
        .gn-theme-toggle:hover{border-color:#06b6d4;background:rgba(6,182,212,.1);}
        .gn-bell{background:none;border:1px solid #2a3a4e;color:#e2e8f0;width:32px;height:32px;border-radius:6px;cursor:pointer;font-size:16px;display:flex;align-items:center;justify-content:center;transition:all .15s;position:relative;}
        .gn-bell:hover{border-color:#f97316;background:rgba(249,115,22,.1);}
        .gn-bell-badge{position:absolute;top:-4px;right:-4px;background:#ef4444;color:#fff;font-size:9px;font-weight:700;min-width:16px;height:16px;border-radius:8px;display:flex;align-items:center;justify-content:center;padding:0 4px;font-family:var(--font-sans,'Inter',sans-serif);}
        .gn-bell-dropdown{position:absolute;top:40px;right:0;width:320px;max-height:400px;overflow-y:auto;background:#111827;border:1px solid #2a3a4e;border-radius:8px;box-shadow:0 8px 30px rgba(0,0,0,.4);z-index:10000;padding:8px 0;}
        .gn-bell-dropdown .gn-ann{padding:10px 14px;border-bottom:1px solid #1a2332;font-size:12px;line-height:1.5;color:#e2e8f0;}
        .gn-bell-dropdown .gn-ann:last-child{border-bottom:none;}
        .gn-bell-dropdown .gn-ann-time{font-size:10px;color:#64748b;margin-top:4px;}
        .gn-bell-dropdown .gn-ann-type{display:inline-block;font-size:9px;font-weight:700;padding:1px 6px;border-radius:4px;margin-right:6px;text-transform:uppercase;}
        .gn-ann-type.info{background:rgba(59,130,246,.15);color:#3b82f6;}
        .gn-ann-type.warning{background:rgba(249,115,22,.15);color:#f97316;}
        .gn-ann-type.danger{background:rgba(239,68,68,.15);color:#ef4444;}
        .gn-bell-empty{padding:20px;text-align:center;color:#64748b;font-size:12px;}
        [data-theme="light"] .gn-bell{border-color:#cbd5e1;color:#1e293b;}
        [data-theme="light"] .gn-bell-dropdown{background:#ffffff;border-color:#cbd5e1;box-shadow:0 8px 30px rgba(0,0,0,.1);}
        [data-theme="light"] .gn-bell-dropdown .gn-ann{color:#1e293b;border-bottom-color:#f1f5f9;}
        [data-theme="light"] .global-nav{background:linear-gradient(135deg,#e2e8f0,#f1f5f9);border-bottom-color:#16a34a;}
        [data-theme="light"] .gn-brand{color:#1e293b;}
        [data-theme="light"] .gn-title{background:linear-gradient(135deg,#16a34a,#0891b2);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
        [data-theme="light"] .gn-link{color:#475569;}
        [data-theme="light"] .gn-link:hover,[data-theme="light"] .gn-link.gn-active{background:#e2e8f0;color:#0891b2;}
        [data-theme="light"] .gn-team{color:#16a34a;background:rgba(22,163,74,.08);border-color:rgba(22,163,74,.2);}
        [data-theme="light"] .gn-logout{border-color:#cbd5e1;color:#64748b;}
        [data-theme="light"] .gn-theme-toggle{border-color:#cbd5e1;color:#1e293b;}
        [data-theme="light"] .gn-mobile-menu{background:#f1f5f9;border-bottom-color:#cbd5e1;}
        @media(max-width:768px){
            .gn-center,.gn-right{display:none;}
            .gn-hamburger{display:block;}
        }
    `;
    document.head.appendChild(style);

    // Inject navbar at top of body
    const container = document.createElement('div');
    container.innerHTML = navHtml;
    document.body.insertBefore(container, document.body.firstChild);

    // Expose global functions
    window.globalNavLogout = function() {
        sessionStorage.removeItem('koth_role');
        sessionStorage.removeItem('koth_team_token');
        sessionStorage.removeItem('koth_admin_token');
        sessionStorage.removeItem('koth_team');
        localStorage.removeItem('koth_role');
        localStorage.removeItem('koth_team_token');
        localStorage.removeItem('koth_admin_token');
        localStorage.removeItem('koth_team');
        window.location.href = '/login';
    };

    window.toggleMobileNav = function() {
        const menu = document.getElementById('gnMobileMenu');
        menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
    };

    window.toggleKothTheme = function() {
        const html = document.documentElement;
        const isLight = html.getAttribute('data-theme') === 'light';
        if (isLight) {
            html.removeAttribute('data-theme');
            localStorage.setItem('koth_theme', 'dark');
        } else {
            html.setAttribute('data-theme', 'light');
            localStorage.setItem('koth_theme', 'light');
        }
        const btn = document.querySelector('.gn-theme-toggle');
        if (btn) btn.textContent = isLight ? '☀️' : '🌙';
    };

    // ── Notification Bell ──
    let _bellOpen = false;
    window.toggleKothBell = function() {
        const dd = document.getElementById('gnBellDropdown');
        _bellOpen = !_bellOpen;
        dd.style.display = _bellOpen ? 'block' : 'none';
        if (_bellOpen) {
            // Mark all as seen
            const badge = document.getElementById('gnBellBadge');
            if (badge) { badge.style.display = 'none'; badge.textContent = '0'; }
            const latest = dd.getAttribute('data-latest-id');
            if (latest) localStorage.setItem('koth_last_ann', latest);
        }
    };

    // Close bell on outside click
    document.addEventListener('click', function(e) {
        if (_bellOpen && !e.target.closest('.gn-bell-wrap')) {
            _bellOpen = false;
            document.getElementById('gnBellDropdown').style.display = 'none';
        }
    });

    async function _loadBellAnnouncements() {
        try {
            const res = await fetch('/api/scoreboard/announcements?limit=10');
            if (!res.ok) return;
            const anns = await res.json();
            const dd = document.getElementById('gnBellDropdown');
            const badge = document.getElementById('gnBellBadge');
            if (!anns.length) {
                dd.innerHTML = '<div class="gn-bell-empty">No announcements</div>';
                return;
            }
            const lastSeen = parseInt(localStorage.getItem('koth_last_ann') || '0', 10);
            dd.setAttribute('data-latest-id', anns[0].id);
            let unread = 0;
            dd.innerHTML = anns.map(a => {
                if (a.id > lastSeen) unread++;
                const t = a.type || 'info';
                const time = a.created_at ? new Date(a.created_at).toLocaleString() : '';
                return `<div class="gn-ann"><span class="gn-ann-type ${escHtml(t)}">${escHtml(t)}</span>${escHtml(a.message)}<div class="gn-ann-time">${time}</div></div>`;
            }).join('');
            if (unread > 0) {
                badge.textContent = unread > 9 ? '9+' : unread;
                badge.style.display = 'flex';
            }
        } catch(e) { /* silent */ }
    }

    // Fetch announcements on load and periodically
    _loadBellAnnouncements();
    setInterval(_loadBellAnnouncements, 30000);

    function escHtml(s) {
        if (!s) return '';
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }
})();
