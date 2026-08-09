import { api, esc, showError, setNavCrumb } from './utils.js';

function isUrl(s) {
    return s.startsWith('http://') || s.startsWith('https://');
}

function buildCard(podcast, grid, el) {
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `<h3>${esc(podcast.title)}</h3><p class="subtitle">${esc(podcast.rss_url)}</p>`;
    card.addEventListener('click', () => { location.hash = '#/podcast/' + podcast.id; });

    // Delivery toggle: muting stops Telegram pushes only — episodes keep being
    // transcribed and summarized, and stay readable here.
    const bellBtn = document.createElement('button');
    let delivery = podcast.telegram_delivery;
    const paintBell = () => {
        bellBtn.textContent = delivery ? '🔔 推播中' : '🔕 已靜音';
        bellBtn.title = delivery ? '點擊停止推播到 Telegram（仍會下載與摘要）' : '點擊恢復推播到 Telegram';
    };
    paintBell();
    bellBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        bellBtn.disabled = true;
        try {
            const updated = await api('/subscriptions/' + podcast.subscription_id + '/delivery', {
                method: 'PATCH',
                body: JSON.stringify({ telegram_delivery: !delivery }),
            });
            delivery = updated.telegram_delivery;
            paintBell();
        } catch (err) {
            alert('切換推播失敗：' + err.message);
        } finally {
            bellBtn.disabled = false;
        }
    });
    card.appendChild(bellBtn);

    const delBtn = document.createElement('button');
    delBtn.className = 'danger';
    delBtn.textContent = '退訂';
    delBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        if (!confirm('確定退訂 ' + podcast.title + '？')) return;
        try {
            await api('/subscriptions/' + podcast.subscription_id, { method: 'DELETE' });
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

async function subscribeUrl(feedUrl, hint = {}, panel, input, resultsList, hideResults, grid, el) {
    const prevErr = panel.querySelector('.error-msg');
    if (prevErr) prevErr.remove();

    // Ensure grid exists before API call so loading card can appear immediately
    if (!grid) {
        const emptyState = el.querySelector('.empty-state');
        if (emptyState) emptyState.remove();
        el.insertAdjacentHTML('beforeend', '<div class="section-label">我的訂閱</div>');
        grid = document.createElement('div');
        grid.className = 'card-grid';
        el.appendChild(grid);
    }

    // Optimistic loading card
    const loadingCard = document.createElement('div');
    loadingCard.className = 'card card-loading';
    loadingCard.innerHTML = `<h3>${esc(hint.name || feedUrl)}</h3><p class="subtitle spinner">訂閱中…</p>`;
    grid.appendChild(loadingCard);
    input.value = '';
    hideResults();

    try {
        const podcast = await api('/subscriptions', { method: 'POST', body: JSON.stringify({ rss_url: feedUrl }) });
        loadingCard.replaceWith(buildCard(podcast, grid, el));
    } catch (err) {
        loadingCard.remove();
        if (grid.children.length === 0) {
            const label = grid.previousElementSibling;
            if (label && label.classList.contains('section-label')) label.remove();
            grid.remove();
            el.insertAdjacentHTML('beforeend', '<div class="empty-state">尚無訂閱，請在上方新增。</div>');
        }
        let errDiv = panel.querySelector('.error-msg');
        if (!errDiv) {
            errDiv = document.createElement('p');
            errDiv.className = 'error-msg';
            panel.appendChild(errDiv);
        }
        errDiv.textContent = err.message;
    }
}

async function searchPodcasts(q, resultsList) {
    resultsList.style.display = 'block';
    resultsList.innerHTML = '<p class="spinner" style="padding:10px 14px;margin:0">搜尋中…</p>';
    try {
        const results = await api('/podcast-catalog/search?q=' + encodeURIComponent(q));
        if (!results.length) {
            resultsList.innerHTML = '<p class="spinner" style="padding:10px 14px;margin:0">無結果</p>';
            return;
        }
        resultsList.innerHTML = '';
        for (const item of results) {
            const row = document.createElement('div');
            row.className = 'search-result-row';
            row.innerHTML = `
                <img src="${esc(item.artwork_url)}" width="48" height="48" onerror="this.style.display='none'">
                <div class="search-result-info">
                    <span class="search-result-name">${esc(item.name)}</span>
                    <span class="search-result-artist">${esc(item.artist)}</span>
                </div>
                <button type="button">+ 訂閱</button>
            `;
            // captured in closure below — grid/el/panel/input/resultsList/hideResults resolved at call time
            row._feedUrl = item.feed_url;
            row._name = item.name;
            resultsList.appendChild(row);
        }
        return results; // caller attaches click handlers after receiving rows
    } catch (err) {
        resultsList.innerHTML = `<p class="error-msg" style="padding:10px 14px;margin:0">${esc(err.message)}</p>`;
    }
}

// ---- Home: subscribed podcasts + subscribe form ----
export async function renderHome(el) {
    el.innerHTML = '<p class="spinner">Loading…</p>';
    setNavCrumb('');
    try {
        const result = await api('/podcasts');
        const podcasts = result.items;
        el.innerHTML = '';

        // Subscribe form
        const panel = document.createElement('div');
        panel.className = 'subscribe-panel';
        panel.innerHTML = '<div class="section-label">新增訂閱</div>';
        const form = document.createElement('form');
        form.innerHTML = `
            <input type="text" id="rss-url" placeholder="搜尋名稱，或貼入 RSS / Apple Podcasts 連結" autocomplete="off">
        `;
        const input = form.querySelector('#rss-url');

        const resultsList = document.createElement('div');
        resultsList.className = 'search-results-list';
        resultsList.style.display = 'none';

        function hideResults() {
            resultsList.style.display = 'none';
            resultsList.innerHTML = '';
        }

        // Attach click handlers to search result rows
        resultsList.addEventListener('click', (e) => {
            const btn = e.target.closest('button');
            if (!btn) return;
            const row = btn.closest('.search-result-row');
            if (!row) return;
            const grid = el.querySelector('.card-grid');
            subscribeUrl(row._feedUrl, { name: row._name }, panel, input, resultsList, hideResults, grid, el);
        });

        let debounceTimer = null;
        input.addEventListener('input', () => {
            clearTimeout(debounceTimer);
            const val = input.value.trim();
            if (val.length < 2) { hideResults(); return; }
            if (isUrl(val)) { hideResults(); return; }
            debounceTimer = setTimeout(() => searchPodcasts(val, resultsList), 300);
        });

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const val = input.value.trim();
            if (!val || !isUrl(val)) return;
            const grid = el.querySelector('.card-grid');
            await subscribeUrl(val, {}, panel, input, resultsList, hideResults, grid, el);
        });

        panel.appendChild(form);
        panel.appendChild(resultsList);
        el.appendChild(panel);

        if (podcasts.length === 0) {
            el.insertAdjacentHTML('beforeend', '<div class="empty-state">尚無訂閱，請在上方新增。</div>');
            return;
        }

        el.insertAdjacentHTML('beforeend', '<div class="section-label">我的訂閱</div>');
        const grid = document.createElement('div');
        grid.className = 'card-grid';
        for (const podcast of podcasts) {
            grid.appendChild(buildCard(podcast, grid, el));
        }
        el.appendChild(grid);
    } catch (err) {
        showError(el, err.message);
    }
}
