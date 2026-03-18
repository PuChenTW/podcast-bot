// ---- API wrapper ----
async function api(path, opts = {}) {
    const resp = await fetch('/api' + path, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
    });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || resp.statusText);
    }
    if (resp.status === 204) return null;
    return resp.json();
}

// ---- Router ----
function route() {
    const hash = location.hash || '#/';
    const content = document.getElementById('content');
    content.innerHTML = '';

    if (hash === '#/' || hash === '') {
        renderHome(content);
    } else if (hash.startsWith('#/podcast/')) {
        const parts = hash.slice('#/podcast/'.length).split('?page=');
        const subId = parts[0];
        const page = parts[1] ? parseInt(parts[1], 10) : 0;
        renderEpisodeList(content, subId, page);
    } else if (hash.startsWith('#/episode/')) {
        const parts = hash.slice('#/episode/'.length).split('/');
        const podId = parts[0];
        const guid = decodeURIComponent(parts.slice(1).join('/'));
        renderEpisodeDetail(content, podId, guid);
    } else {
        content.innerHTML = '<p>Page not found.</p>';
    }
}

window.addEventListener('hashchange', route);
window.addEventListener('load', route);

// ---- Home: subscribed podcasts + subscribe form ----
function buildCard(sub, grid, el) {
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `<h3>${esc(sub.podcast_title)}</h3><p class="subtitle">${esc(sub.rss_url)}</p>`;
    card.addEventListener('click', () => { location.hash = '#/podcast/' + sub.id; });

    const delBtn = document.createElement('button');
    delBtn.className = 'danger';
    delBtn.textContent = '退訂';
    delBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        if (!confirm('確定退訂 ' + sub.podcast_title + '？')) return;
        try {
            await api('/subscriptions/' + sub.id, { method: 'DELETE' });
            card.remove();
            if (grid.children.length === 0) {
                const label = grid.previousElementSibling;
                if (label && label.classList.contains('section-label')) label.remove();
                grid.remove();
                el.insertAdjacentHTML('beforeend', '<div class="empty-state">尚無訂閱，請在上方新增。</div>');
            }
        } catch (err) {
            alert('退訂失敗：' + err.message);
        }
    });
    card.appendChild(delBtn);
    return card;
}

async function renderHome(el) {
    el.innerHTML = '<p class="spinner">Loading…</p>';
    setNavCrumb('');
    try {
        const subs = await api('/subscriptions');
        el.innerHTML = '';

        // Subscribe form
        const panel = document.createElement('div');
        panel.className = 'subscribe-panel';
        panel.innerHTML = '<div class="section-label">新增訂閱</div>';
        const form = document.createElement('form');
        form.innerHTML = `
            <input type="url" id="rss-url" placeholder="RSS 或 Apple Podcasts 網址" required>
            <button type="submit">訂閱</button>
        `;
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const btn = form.querySelector('button');
            const input = document.getElementById('rss-url');
            btn.disabled = true;
            btn.textContent = '訂閱中…';
            try {
                const sub = await api('/subscriptions', { method: 'POST', body: JSON.stringify({ rss_url: input.value }) });
                let grid = el.querySelector('.card-grid');
                if (!grid) {
                    const emptyState = el.querySelector('.empty-state');
                    if (emptyState) emptyState.remove();
                    el.insertAdjacentHTML('beforeend', '<div class="section-label">我的訂閱</div>');
                    grid = document.createElement('div');
                    grid.className = 'card-grid';
                    el.appendChild(grid);
                }
                grid.appendChild(buildCard(sub, grid, el));
                input.value = '';
                const prevErr = panel.querySelector('.error-msg');
                if (prevErr) prevErr.remove();
            } catch (err) {
                let errDiv = panel.querySelector('.error-msg');
                if (!errDiv) {
                    errDiv = document.createElement('p');
                    errDiv.className = 'error-msg';
                    panel.appendChild(errDiv);
                }
                errDiv.textContent = err.message;
            } finally {
                btn.disabled = false;
                btn.textContent = '訂閱';
            }
        });
        panel.appendChild(form);
        el.appendChild(panel);

        if (subs.length === 0) {
            el.insertAdjacentHTML('beforeend', '<div class="empty-state">尚無訂閱，請在上方新增。</div>');
            return;
        }

        el.insertAdjacentHTML('beforeend', '<div class="section-label">我的訂閱</div>');
        const grid = document.createElement('div');
        grid.className = 'card-grid';
        for (const sub of subs) {
            grid.appendChild(buildCard(sub, grid, el));
        }
        el.appendChild(grid);
    } catch (err) {
        showError(el, err.message);
    }
}

// ---- Episode list ----
async function renderEpisodeList(el, subId, page = 0) {
    el.innerHTML = '<p class="spinner">載入中…</p>';
    try {
        const [subs, result] = await Promise.all([
            api('/subscriptions'),
            api('/subscriptions/' + subId + '/episodes?page=' + page),
        ]);
        const sub = subs.find(s => s.id === subId);
        if (!sub) { showError(el, '找不到訂閱'); return; }
        const podId = sub.podcast_id;
        if (!result || !result.episodes) { showError(el, '伺服器回應異常'); return; }
        const episodes = result.episodes;

        // Breadcrumb navbar
        setNavCrumb(esc(sub.podcast_title));
        el.innerHTML = '';

        // Custom prompt editor
        const promptDetails = document.createElement('details');
        promptDetails.className = 'prompt-details';
        promptDetails.innerHTML = '<summary>自訂摘要提示詞</summary>';
        const promptArea = document.createElement('textarea');
        promptArea.className = 'prompt-area';
        promptArea.placeholder = '留空則使用預設提示詞';
        promptArea.value = sub.custom_prompt || '';
        const saveBtn = document.createElement('button');
        saveBtn.className = 'secondary';
        saveBtn.textContent = '儲存';
        saveBtn.style.marginTop = '0.5rem';
        saveBtn.addEventListener('click', async () => {
            await api('/subscriptions/' + subId + '/prompt', {
                method: 'PUT',
                body: JSON.stringify({ prompt: promptArea.value || null }),
            });
            saveBtn.textContent = '已儲存！';
            setTimeout(() => { saveBtn.textContent = '儲存'; }, 1500);
        });
        promptDetails.appendChild(promptArea);
        promptDetails.appendChild(saveBtn);
        el.appendChild(promptDetails);

        // Refresh button
        const refreshBtn = document.createElement('button');
        refreshBtn.className = 'secondary';
        refreshBtn.textContent = '重新整理';
        refreshBtn.style.marginBottom = '1rem';
        refreshBtn.addEventListener('click', async () => {
            refreshBtn.disabled = true;
            refreshBtn.textContent = '更新中…';
            try {
                const res = await api('/subscriptions/' + subId + '/refresh', { method: 'POST' });
                renderEpisodeList(el, subId, page);
            } catch (err) {
                refreshBtn.textContent = '錯誤：' + err.message;
                refreshBtn.disabled = false;
            }
        });
        el.appendChild(refreshBtn);

        if (episodes.length === 0 && page === 0) {
            el.insertAdjacentHTML('beforeend', '<div class="empty-state">尚無集數，Bot 每 6 小時自動抓取。</div>');
            return;
        }

        const list = document.createElement('div');
        list.className = 'episode-list';
        for (const ep of episodes) {
            const row = document.createElement('div');
            row.className = 'episode-row';
            row.innerHTML = `
                <span class="episode-title">${esc(ep.title || ep.episode_guid)}</span>
                <span class="episode-meta">
                    <span class="episode-date">${ep.published_at ? ep.published_at.slice(0,10) : ''}</span>
                    <span class="badge ${ep.has_summary ? 'badge-yes' : 'badge-no'}">${ep.has_summary ? '✓ 摘要' : '無摘要'}</span>
                </span>
            `;
            row.addEventListener('click', () => {
                location.hash = '#/episode/' + podId + '/' + encodeURIComponent(ep.episode_guid);
            });
            list.appendChild(row);
        }
        el.appendChild(list);

        // Pagination
        const pag = document.createElement('div');
        pag.className = 'pagination';
        if (result.has_prev) {
            const prevBtn = document.createElement('button');
            prevBtn.className = 'secondary';
            prevBtn.textContent = '← 較新';
            prevBtn.addEventListener('click', () => { location.hash = '#/podcast/' + subId + '?page=' + (page - 1); });
            pag.appendChild(prevBtn);
        } else {
            pag.appendChild(document.createElement('span'));
        }
        pag.insertAdjacentHTML('beforeend', `<span class="page-info">第 ${page + 1} 頁</span>`);
        if (result.has_next) {
            const nextBtn = document.createElement('button');
            nextBtn.className = 'secondary';
            nextBtn.textContent = '較舊 →';
            nextBtn.addEventListener('click', () => { location.hash = '#/podcast/' + subId + '?page=' + (page + 1); });
            pag.appendChild(nextBtn);
        } else {
            pag.appendChild(document.createElement('span'));
        }
        el.appendChild(pag);
    } catch (err) {
        showError(el, err.message);
    }
}

// ---- Episode detail ----
async function renderEpisodeDetail(el, podId, guid) {
    el.innerHTML = '<p class="spinner">載入中…</p>';
    try {
        const detail = await api('/podcasts/' + podId + '/episodes/' + encodeURIComponent(guid) + '/detail');

        setNavCrumb(esc(detail.title || guid));
        el.innerHTML = '';

        el.insertAdjacentHTML('beforeend', `<h2 class="episode-detail-title">${esc(detail.title || guid)}</h2>`);

        // Tabs
        const tabNames = ['摘要', '說明', '逐字稿', '精簡版', '💬 討論'];
        const tabBar = document.createElement('div');
        tabBar.className = 'tabs';
        const tabPanels = [];

        // Summary panel (created early so regenBtn can reference it)
        const summaryPanel = document.createElement('div');
        summaryPanel.className = 'tab-content active';
        summaryPanel.innerHTML = detail.summary
            ? marked.parse(detail.summary)
            : '<p class="empty-state">尚無摘要。</p>';

        const regenBtn = document.createElement('button');
        regenBtn.textContent = '↺';
        regenBtn.title = '重新生成摘要';
        regenBtn.className = 'regen-btn';
        regenBtn.addEventListener('click', () => startRegenerate(podId, guid, summaryPanel, regenBtn));

        let chatInitialized = false;
        tabNames.forEach((name, i) => {
            const btn = document.createElement('button');
            btn.className = 'tab-btn' + (i === 0 ? ' active' : '');
            btn.textContent = name;
            btn.addEventListener('click', () => {
                tabBar.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                tabPanels.forEach(p => p.classList.remove('active'));
                btn.classList.add('active');
                tabPanels[i].classList.add('active');
                // Lazy-init chat panel on first open
                if (i === 4 && !chatInitialized) {
                    chatInitialized = true;
                    buildChatPanel(chatPanel, podId, guid, detail);
                }
            });
            tabBar.appendChild(btn);
        });
        tabBar.appendChild(regenBtn);
        el.appendChild(tabBar);

        // Tab panel wrapper
        const wrapper = document.createElement('div');
        wrapper.className = 'tab-panel-wrapper';

        tabPanels.push(summaryPanel);
        wrapper.appendChild(summaryPanel);

        const descPanel = document.createElement('div');
        descPanel.className = 'tab-content';
        descPanel.innerHTML = detail.description
            ? `<div class="description-content">${detail.description}</div>`
            : '<p class="empty-state">無說明。</p>';
        tabPanels.push(descPanel);
        wrapper.appendChild(descPanel);

        const transcriptPanel = document.createElement('div');
        transcriptPanel.className = 'tab-content';
        transcriptPanel.innerHTML = detail.transcript
            ? `<pre class="transcript-pre">${esc(detail.transcript)}</pre>`
            : '<p class="empty-state">無逐字稿。</p>';
        tabPanels.push(transcriptPanel);
        wrapper.appendChild(transcriptPanel);

        const condensedPanel = document.createElement('div');
        condensedPanel.className = 'tab-content';
        condensedPanel.innerHTML = detail.condensed_transcript
            ? `<pre class="transcript-pre">${esc(detail.condensed_transcript)}</pre>`
            : '<p class="empty-state">無精簡版逐字稿。</p>';
        tabPanels.push(condensedPanel);
        wrapper.appendChild(condensedPanel);

        // 5th tab: chat panel (built lazily on first activation)
        const chatPanel = document.createElement('div');
        chatPanel.className = 'tab-content';
        tabPanels.push(chatPanel);
        wrapper.appendChild(chatPanel);

        el.appendChild(wrapper);
    } catch (err) {
        showError(el, err.message);
    }
}

async function startRegenerate(podId, guid, summaryPanel, regenBtn) {
    regenBtn.disabled = true;
    regenBtn.textContent = '↻';
    summaryPanel.innerHTML = '<p class="empty-state">重新生成中，請稍候…</p>';
    try {
        const { job_id } = await api('/podcasts/' + podId + '/episodes/' + encodeURIComponent(guid) + '/regenerate', { method: 'POST' });
        pollJob(job_id,
            (result) => {
                summaryPanel.innerHTML = marked.parse(result);
                regenBtn.disabled = false;
                regenBtn.textContent = '↺';
            },
            (errMsg) => {
                summaryPanel.innerHTML = `<p class="error-msg">Error: ${esc(errMsg)}</p>`;
                regenBtn.disabled = false;
                regenBtn.textContent = '↺';
            }
        );
    } catch (err) {
        summaryPanel.innerHTML = `<p class="error-msg">Error: ${esc(err.message)}</p>`;
        regenBtn.disabled = false;
        regenBtn.textContent = '↺';
    }
}

// ---- Chat panel ----
function buildChatPanel(panel, podId, guid, detail) {
    let historyJson = '';

    panel.innerHTML = `
        <div class="chat-panel">
            <div class="chat-history" id="chat-history-area"></div>
            <div class="chat-input-row">
                <input type="text" id="chat-input" placeholder="輸入訊息，按 Enter 送出…" autocomplete="off">
                <button id="chat-send-btn">送出</button>
            </div>
        </div>
    `;

    const historyArea = panel.querySelector('#chat-history-area');
    const inputEl = panel.querySelector('#chat-input');
    const sendBtn = panel.querySelector('#chat-send-btn');

    function appendBubble(role, text) {
        const msg = document.createElement('div');
        msg.className = 'chat-msg ' + (role === 'agent' ? 'chat-msg-agent' : 'chat-msg-user');
        const bubble = document.createElement('div');
        bubble.className = 'bubble';
        bubble.textContent = text;
        msg.appendChild(bubble);
        historyArea.appendChild(msg);
        historyArea.scrollTop = historyArea.scrollHeight;
        return bubble;
    }

    async function sendMessage(message) {
        inputEl.disabled = true;
        sendBtn.disabled = true;

        if (message !== '__init__') {
            appendBubble('user', message);
        }

        const agentBubble = appendBubble('agent', '…');
        const cursor = document.createElement('span');
        cursor.className = 'chat-cursor';
        agentBubble.appendChild(cursor);
        historyArea.scrollTop = historyArea.scrollHeight;

        await streamChat(
            podId, guid, message, historyJson,
            agentBubble, cursor,
            (newHistoryJson) => { historyJson = newHistoryJson; },
            (errMsg) => {
                agentBubble.textContent = '錯誤：' + errMsg;
                agentBubble.style.color = '#ef4444';
            }
        );

        inputEl.disabled = false;
        sendBtn.disabled = false;
        inputEl.focus();
    }

    sendBtn.addEventListener('click', () => {
        const msg = inputEl.value.trim();
        if (!msg) return;
        inputEl.value = '';
        sendMessage(msg);
    });

    inputEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
            e.preventDefault();
            const msg = inputEl.value.trim();
            if (!msg) return;
            inputEl.value = '';
            sendMessage(msg);
        }
    });

    // Auto-send opening message
    sendMessage('__init__');
}


async function streamChat(podId, guid, message, historyJson, bubbleEl, cursorEl, onHistory, onError) {
    const url = '/api/podcasts/' + podId + '/episodes/' + encodeURIComponent(guid) + '/chat';
    let resp;
    try {
        resp = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, history: historyJson }),
        });
    } catch (err) {
        cursorEl.remove();
        onError(err.message);
        return;
    }

    if (!resp.ok) {
        cursorEl.remove();
        const data = await resp.json().catch(() => ({ detail: resp.statusText }));
        onError(data.detail || resp.statusText);
        return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let pendingEvent = '';
    let firstChunk = true;
    let rawText = '';  // accumulates full response text for final markdown render

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop(); // carry incomplete last line forward

        for (const line of lines) {
            if (line === '') {
                pendingEvent = '';
            } else if (line.startsWith('event: ')) {
                pendingEvent = line.slice('event: '.length).trim();
            } else if (line.startsWith('data: ')) {
                const data = line.slice('data: '.length);
                if (pendingEvent === 'history') {
                    onHistory(data);
                    pendingEvent = '';
                } else if (pendingEvent === 'error') {
                    cursorEl.remove();
                    onError(data);
                    pendingEvent = '';
                    return;
                } else {
                    if (firstChunk) {
                        firstChunk = false;
                        Array.from(bubbleEl.childNodes).forEach(n => {
                            if (n !== cursorEl) n.remove();
                        });
                    }
                    const text = data.replace(/\\n/g, '\n');
                    rawText += text;
                    cursorEl.insertAdjacentText('beforebegin', text);
                    const hist = bubbleEl.closest('.chat-history');
                    if (hist) hist.scrollTop = hist.scrollHeight;
                }
            }
        }
    }

    cursorEl.remove();
    // Re-render accumulated text as markdown now that streaming is complete
    if (rawText) {
        bubbleEl.innerHTML = marked.parse(rawText);
    }
    const hist = bubbleEl.closest('.chat-history');
    if (hist) hist.scrollTop = hist.scrollHeight;
}


function pollJob(jobId, onDone, onError) {
    setTimeout(async () => {
        try {
            const job = await api('/jobs/' + jobId);
            if (job.status === 'done') {
                onDone(job.result);
            } else if (job.status === 'error') {
                onError(job.error || 'Unknown error');
            } else {
                pollJob(jobId, onDone, onError); // keep polling
            }
        } catch (err) {
            onError(err.message);
        }
    }, 2000);
}

// ---- Navbar breadcrumb ----
function setNavCrumb(label) {
    const navbar = document.getElementById('navbar');
    if (!navbar) return;
    navbar.querySelectorAll('.nav-sep, .nav-crumb').forEach(el => el.remove());
    if (label) {
        navbar.insertAdjacentHTML('beforeend',
            `<span class="nav-sep">/</span><span class="nav-crumb">${label}</span>`);
    }
}

// ---- Utilities ----
function esc(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function showError(el, msg) {
    el.innerHTML = `<p class="error-msg">Error: ${esc(msg)}</p>`;
}
