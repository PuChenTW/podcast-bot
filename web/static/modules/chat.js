import { api, esc } from './utils.js';

// ---- Chat panel ----
export function buildChatPanel(panel, podId, guid, detail) {
    let historyJson = '';

    panel.innerHTML = `
        <div class="chat-panel">
            <div class="chat-history" id="chat-history-area"></div>
            <div class="chat-input-row">
                <textarea id="chat-input" placeholder="輸入訊息，按 Enter 送出；Shift+Enter 換行" autocomplete="off" rows="1"></textarea>
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

    function autoResize() {
        inputEl.style.height = 'auto';
        inputEl.style.height = inputEl.scrollHeight + 'px';
    }

    function submitInput() {
        const msg = inputEl.value.trim();
        if (!msg) return;
        inputEl.value = '';
        inputEl.style.height = 'auto';
        sendMessage(msg);
    }

    inputEl.addEventListener('input', autoResize);

    sendBtn.addEventListener('click', submitInput);

    inputEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            if (e.isComposing) return;
            e.preventDefault();
            submitInput();
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
