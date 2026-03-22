import { api, esc, showError, setNavCrumb, pollJob } from './utils.js';
import { buildChatPanel } from './chat.js';

function buildGeneratePanel(apiPath, targetTextarea) {
    const toggleBtn = document.createElement('button');
    toggleBtn.className = 'secondary';
    toggleBtn.textContent = '自動生成';
    toggleBtn.style.marginTop = '0.5rem';

    const panel = document.createElement('div');
    panel.className = 'generate-panel';
    panel.hidden = true;
    panel.style.marginTop = '0.5rem';

    const descArea = document.createElement('textarea');
    descArea.className = 'prompt-area';
    descArea.placeholder = '（可選）描述你想要的風格，留空則 AI 根據 Podcast 標題自動判斷';
    descArea.rows = 2;

    const genBtn = document.createElement('button');
    genBtn.className = 'secondary';
    genBtn.textContent = '生成';
    genBtn.style.marginTop = '0.25rem';

    genBtn.addEventListener('click', async () => {
        genBtn.disabled = true;
        genBtn.textContent = '生成中…';
        try {
            const data = await api(apiPath, {
                method: 'POST',
                body: JSON.stringify({ description: descArea.value }),
            });
            targetTextarea.value = data.prompt;
            genBtn.textContent = '生成';
        } catch (err) {
            genBtn.textContent = '錯誤：' + err.message;
            setTimeout(() => { genBtn.textContent = '生成'; }, 2000);
        } finally {
            genBtn.disabled = false;
        }
    });

    toggleBtn.addEventListener('click', () => {
        panel.hidden = !panel.hidden;
    });

    panel.appendChild(descArea);
    panel.appendChild(genBtn);
    return { toggleBtn, panel };
}

// ---- Episode list ----
export async function renderEpisodeList(el, subId, page = 0) {
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
        const { toggleBtn: promptGenToggle, panel: promptGenPanel } =
            buildGeneratePanel('/subscriptions/' + subId + '/generate-prompt', promptArea);
        promptDetails.appendChild(promptGenToggle);
        promptDetails.appendChild(promptGenPanel);
        el.appendChild(promptDetails);

        // Custom chat prompt editor
        const chatPromptDetails = document.createElement('details');
        chatPromptDetails.className = 'prompt-details';
        chatPromptDetails.innerHTML = '<summary>自訂討論提示詞</summary>';
        const chatPromptArea = document.createElement('textarea');
        chatPromptArea.className = 'prompt-area';
        chatPromptArea.placeholder = '留空則使用預設討論風格（例如：你是一位蘇格拉底式的導師，請引導我深入思考）';
        chatPromptArea.value = sub.chat_prompt || '';
        const chatSaveBtn = document.createElement('button');
        chatSaveBtn.className = 'secondary';
        chatSaveBtn.textContent = '儲存';
        chatSaveBtn.style.marginTop = '0.5rem';
        chatSaveBtn.addEventListener('click', async () => {
            await api('/subscriptions/' + subId + '/chat-prompt', {
                method: 'PUT',
                body: JSON.stringify({ prompt: chatPromptArea.value || null }),
            });
            chatSaveBtn.textContent = '已儲存！';
            setTimeout(() => { chatSaveBtn.textContent = '儲存'; }, 1500);
        });
        chatPromptDetails.appendChild(chatPromptArea);
        chatPromptDetails.appendChild(chatSaveBtn);
        const { toggleBtn: chatGenToggle, panel: chatGenPanel } =
            buildGeneratePanel('/subscriptions/' + subId + '/generate-chat-prompt', chatPromptArea);
        chatPromptDetails.appendChild(chatGenToggle);
        chatPromptDetails.appendChild(chatGenPanel);
        el.appendChild(chatPromptDetails);

        // Refresh button
        const refreshBtn = document.createElement('button');
        refreshBtn.className = 'secondary';
        refreshBtn.textContent = '重新整理';
        refreshBtn.style.marginBottom = '1rem';
        refreshBtn.addEventListener('click', async () => {
            refreshBtn.disabled = true;
            refreshBtn.textContent = '更新中…';
            try {
                await api('/subscriptions/' + subId + '/refresh', { method: 'POST' });
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
export async function renderEpisodeDetail(el, podId, guid) {
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
        regenBtn.addEventListener('click', () => startRegenerate(podId, guid, summaryPanel, transcriptPanel, regenBtn));

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

async function startRegenerate(podId, guid, summaryPanel, transcriptPanel, regenBtn) {
    regenBtn.disabled = true;
    regenBtn.textContent = '↻';
    summaryPanel.innerHTML = '<p class="empty-state">重新生成中，請稍候…</p>';
    try {
        const { job_id } = await api('/podcasts/' + podId + '/episodes/' + encodeURIComponent(guid) + '/regenerate', { method: 'POST' });
        pollJob(job_id,
            async (result) => {
                summaryPanel.innerHTML = marked.parse(result);
                regenBtn.disabled = false;
                regenBtn.textContent = '↺';
                // Fetch updated detail to get the newly saved transcript
                try {
                    const updated = await api('/podcasts/' + podId + '/episodes/' + encodeURIComponent(guid) + '/detail');
                    transcriptPanel.innerHTML = updated.transcript
                        ? `<pre class="transcript-pre">${esc(updated.transcript)}</pre>`
                        : '<p class="empty-state">無逐字稿。</p>';
                } catch (_) { /* non-fatal: transcript panel stays stale */ }
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
