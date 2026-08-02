import { api, esc, showError, setNavCrumb, pollJob } from './utils.js';
import { buildChatPanel } from './chat.js';

function buildGeneratePanel(apiPath, kind, targetTextarea) {
    const toggleBtn = document.createElement('button');
    toggleBtn.className = 'secondary';
    toggleBtn.textContent = '自動生成';
    toggleBtn.style.marginTop = '0.5rem';
    toggleBtn.style.marginLeft = '0.5rem';

    const panel = document.createElement('div');
    panel.className = 'generate-panel';
    panel.hidden = true;
    panel.style.marginTop = '0.5rem';

    const descArea = document.createElement('textarea');
    descArea.className = 'prompt-area';
    descArea.placeholder = '（可選）描述你想要的風格';
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
                body: JSON.stringify({ kind, description: descArea.value }),
            });
            targetTextarea.value = data.prompt;
        } catch (err) {
            genBtn.textContent = '錯誤：' + err.message;
            setTimeout(() => { genBtn.textContent = '生成'; }, 2000);
            return;
        } finally {
            genBtn.disabled = false;
        }
        genBtn.textContent = '生成';
    });
    toggleBtn.addEventListener('click', () => { panel.hidden = !panel.hidden; });
    panel.appendChild(descArea);
    panel.appendChild(genBtn);
    return { toggleBtn, panel };
}

function appendPromptEditor(container, title, value, onSave, draftPath, kind) {
    const details = document.createElement('details');
    details.className = 'prompt-details';
    details.innerHTML = `<summary>${title}</summary>`;
    const textarea = document.createElement('textarea');
    textarea.className = 'prompt-area';
    textarea.placeholder = '留空則使用預設提示詞';
    textarea.value = value || '';
    const saveBtn = document.createElement('button');
    saveBtn.className = 'secondary';
    saveBtn.textContent = '儲存';
    saveBtn.style.marginTop = '0.5rem';
    saveBtn.addEventListener('click', async () => {
        await onSave(textarea.value || null);
        saveBtn.textContent = '已儲存！';
        setTimeout(() => { saveBtn.textContent = '儲存'; }, 1500);
    });
    const generated = buildGeneratePanel(draftPath, kind, textarea);
    details.appendChild(textarea);
    details.appendChild(saveBtn);
    details.appendChild(generated.toggleBtn);
    details.appendChild(generated.panel);
    container.appendChild(details);
}

export async function renderEpisodeList(el, podcastId, cursor = null, page = 0) {
    el.innerHTML = '<p class="spinner">載入中…</p>';
    try {
        const podcast = await api('/podcasts/' + podcastId);
        const query = cursor ? '?cursor=' + encodeURIComponent(cursor) : '';
        const [prompts, result] = await Promise.all([
            api('/subscriptions/' + podcast.subscription_id + '/prompts'),
            api('/podcasts/' + podcastId + '/episodes' + query),
        ]);
        setNavCrumb(esc(podcast.title));
        el.innerHTML = '';

        const scrollable = document.createElement('div');
        scrollable.className = 'scroll-pane';
        el.appendChild(scrollable);
        const promptPath = '/subscriptions/' + podcast.subscription_id;
        appendPromptEditor(
            scrollable,
            '自訂摘要提示詞',
            prompts.summary_prompt,
            value => api(promptPath + '/prompts', { method: 'PATCH', body: JSON.stringify({ summary_prompt: value }) }),
            promptPath + '/prompt-drafts',
            'summary',
        );
        appendPromptEditor(
            scrollable,
            '自訂討論提示詞',
            prompts.chat_prompt,
            value => api(promptPath + '/prompts', { method: 'PATCH', body: JSON.stringify({ chat_prompt: value }) }),
            promptPath + '/prompt-drafts',
            'chat',
        );

        const refreshBtn = document.createElement('button');
        refreshBtn.className = 'secondary';
        refreshBtn.textContent = '重新整理';
        refreshBtn.style.marginBottom = '1rem';
        refreshBtn.addEventListener('click', async () => {
            refreshBtn.disabled = true;
            refreshBtn.textContent = '更新中…';
            try {
                await api('/podcasts/' + podcastId + '/sync', { method: 'POST' });
                renderEpisodeList(el, podcastId);
            } catch (err) {
                refreshBtn.textContent = '錯誤：' + err.message;
                refreshBtn.disabled = false;
            }
        });
        scrollable.appendChild(refreshBtn);

        if (result.items.length === 0) {
            scrollable.insertAdjacentHTML('beforeend', '<div class="empty-state">尚無集數。</div>');
            return;
        }
        const list = document.createElement('div');
        list.className = 'episode-list';
        for (const episode of result.items) {
            const row = document.createElement('div');
            row.className = 'episode-row';
            row.innerHTML = `
                <span class="episode-title">${esc(episode.title || episode.id)}</span>
                <span class="episode-meta">
                    <span class="episode-date">${episode.published_at ? episode.published_at.slice(0, 10) : ''}</span>
                    <span class="badge ${episode.has_summary ? 'badge-yes' : 'badge-no'}">${episode.has_summary ? '✓ 摘要' : '無摘要'}</span>
                </span>`;
            row.addEventListener('click', () => { location.hash = '#/episode/' + episode.id; });
            list.appendChild(row);
        }
        scrollable.appendChild(list);

        if (result.next_cursor) {
            const pagination = document.createElement('div');
            pagination.className = 'pagination';
            pagination.appendChild(document.createElement('span'));
            pagination.insertAdjacentHTML('beforeend', `<span class="page-info">第 ${page + 1} 頁</span>`);
            const nextBtn = document.createElement('button');
            nextBtn.className = 'secondary';
            nextBtn.textContent = '較舊 →';
            nextBtn.addEventListener('click', () => {
                location.hash = '#/podcast/' + podcastId + '?cursor=' + encodeURIComponent(result.next_cursor) + '&page=' + (page + 1);
            });
            pagination.appendChild(nextBtn);
            scrollable.appendChild(pagination);
        }
    } catch (err) {
        showError(el, err.message);
    }
}

async function optionalResource(path) {
    try {
        return await api(path);
    } catch (err) {
        if (err.status === 404) return null;
        throw err;
    }
}

export async function renderEpisodeDetail(el, episodeId) {
    el.innerHTML = '<p class="spinner">載入中…</p>';
    try {
        const [detail, summary, transcript] = await Promise.all([
            api('/episodes/' + episodeId),
            optionalResource('/episodes/' + episodeId + '/summary'),
            optionalResource('/episodes/' + episodeId + '/transcript'),
        ]);
        setNavCrumb(esc(detail.title || episodeId));
        el.innerHTML = `<h2 class="episode-detail-title">${esc(detail.title || episodeId)}</h2>`;

        const tabNames = ['摘要', '說明', '逐字稿', '💬 討論'];
        const tabBar = document.createElement('div');
        tabBar.className = 'tabs';
        const tabPanels = [];
        const summaryPanel = document.createElement('div');
        summaryPanel.className = 'tab-content active';
        summaryPanel.innerHTML = summary ? marked.parse(summary.content) : '<p class="empty-state">尚無摘要。</p>';
        const regenBtn = document.createElement('button');
        regenBtn.textContent = '↺';
        regenBtn.title = '重新生成摘要';
        regenBtn.className = 'regen-btn';
        regenBtn.addEventListener('click', () => startRegenerate(episodeId, summaryPanel, regenBtn));

        const transcriptRegenBtn = document.createElement('button');
        transcriptRegenBtn.textContent = '↺';
        transcriptRegenBtn.title = '重新抓取逐字稿';
        transcriptRegenBtn.className = 'regen-btn';
        transcriptRegenBtn.hidden = true;
        transcriptRegenBtn.addEventListener('click', () => startTranscriptRegenerate(episodeId, transcriptPanelRef, transcriptRegenBtn));

        let chatInitialized = false;
        tabNames.forEach((name, index) => {
            const button = document.createElement('button');
            button.className = 'tab-btn' + (index === 0 ? ' active' : '');
            button.textContent = name;
            button.addEventListener('click', () => {
                tabBar.querySelectorAll('.tab-btn').forEach(item => item.classList.remove('active'));
                tabPanels.forEach(item => item.classList.remove('active'));
                button.classList.add('active');
                tabPanels[index].classList.add('active');
                regenBtn.hidden = index !== 0;
                transcriptRegenBtn.hidden = index !== 2;
                if (index === 3 && !chatInitialized) {
                    chatInitialized = true;
                    buildChatPanel(chatPanel, episodeId, detail);
                }
            });
            tabBar.appendChild(button);
        });
        tabBar.appendChild(regenBtn);
        tabBar.appendChild(transcriptRegenBtn);
        el.appendChild(tabBar);

        const wrapper = document.createElement('div');
        wrapper.className = 'tab-panel-wrapper';
        tabPanels.push(summaryPanel);
        wrapper.appendChild(summaryPanel);
        const descPanel = document.createElement('div');
        descPanel.className = 'tab-content';
        descPanel.innerHTML = detail.description ? `<div class="description-content">${detail.description}</div>` : '<p class="empty-state">無說明。</p>';
        tabPanels.push(descPanel);
        wrapper.appendChild(descPanel);
        const transcriptPanelRef = document.createElement('div');
        transcriptPanelRef.className = 'tab-content';
        transcriptPanelRef.innerHTML = transcript ? `<pre class="transcript-pre">${esc(transcript.content)}</pre>` : '<p class="empty-state">無逐字稿。</p>';
        tabPanels.push(transcriptPanelRef);
        wrapper.appendChild(transcriptPanelRef);
        const chatPanel = document.createElement('div');
        chatPanel.className = 'tab-content';
        tabPanels.push(chatPanel);
        wrapper.appendChild(chatPanel);
        el.appendChild(wrapper);
    } catch (err) {
        showError(el, err.message);
    }
}

async function startRegenerate(episodeId, summaryPanel, regenBtn) {
    regenBtn.disabled = true;
    regenBtn.textContent = '↻';
    summaryPanel.innerHTML = '<p class="empty-state">重新生成中，請稍候…</p>';
    try {
        const job = await api('/episodes/' + episodeId + '/summary-jobs', { method: 'POST' });
        pollJob(job.id,
            async () => {
                const summary = await api('/episodes/' + episodeId + '/summary');
                summaryPanel.innerHTML = marked.parse(summary.content);
                regenBtn.disabled = false;
                regenBtn.textContent = '↺';
            },
            error => {
                summaryPanel.innerHTML = `<p class="error-msg">Error: ${esc(error)}</p>`;
                regenBtn.disabled = false;
                regenBtn.textContent = '↺';
            },
        );
    } catch (err) {
        summaryPanel.innerHTML = `<p class="error-msg">Error: ${esc(err.message)}</p>`;
        regenBtn.disabled = false;
        regenBtn.textContent = '↺';
    }
}

async function startTranscriptRegenerate(episodeId, transcriptPanel, regenBtn) {
    regenBtn.disabled = true;
    regenBtn.textContent = '↻';
    transcriptPanel.innerHTML = '<p class="empty-state">重新抓取中，請稍候…</p>';
    try {
        const job = await api('/episodes/' + episodeId + '/transcript-jobs', { method: 'POST' });
        pollJob(job.id,
            async () => {
                const transcript = await api('/episodes/' + episodeId + '/transcript');
                transcriptPanel.innerHTML = `<pre class="transcript-pre">${esc(transcript.content)}</pre>`;
                regenBtn.disabled = false;
                regenBtn.textContent = '↺';
            },
            error => {
                transcriptPanel.innerHTML = `<p class="error-msg">Error: ${esc(error)}</p>`;
                regenBtn.disabled = false;
                regenBtn.textContent = '↺';
            },
        );
    } catch (err) {
        transcriptPanel.innerHTML = `<p class="error-msg">Error: ${esc(err.message)}</p>`;
        regenBtn.disabled = false;
        regenBtn.textContent = '↺';
    }
}
