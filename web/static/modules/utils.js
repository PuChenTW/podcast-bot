// ---- API wrapper ----
export async function api(path, opts = {}) {
    const resp = await fetch(new URL('api/v1' + path, document.baseURI), {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
    });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        const error = new Error(err.detail || err.error?.message || resp.statusText);
        error.status = resp.status;
        throw error;
    }
    if (resp.status === 204) return null;
    return resp.json();
}

// ---- Job polling ----
export function pollJob(jobId, onDone, onError) {
    setTimeout(async () => {
        try {
            const job = await api('/jobs/' + jobId);
            if (job.status === 'done') {
                onDone(job.result_url);
            } else if (job.status === 'error') {
                onError(job.error_message || 'Unknown error');
            } else {
                pollJob(jobId, onDone, onError); // keep polling
            }
        } catch (err) {
            onError(err.message);
        }
    }, 2000);
}

// ---- Navbar breadcrumb ----
export function setNavCrumb(label) {
    const navbar = document.getElementById('navbar');
    if (!navbar) return;
    navbar.querySelectorAll('.nav-sep, .nav-crumb').forEach(el => el.remove());
    if (label) {
        const toggle = navbar.querySelector('#theme-toggle');
        const html = `<span class="nav-sep">/</span><span class="nav-crumb">${label}</span>`;
        if (toggle) {
            toggle.insertAdjacentHTML('beforebegin', html);
        } else {
            navbar.insertAdjacentHTML('beforeend', html);
        }
    }
}

// ---- HTML escaping ----
export function esc(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// ---- Error display ----
export function showError(el, msg) {
    el.innerHTML = `<p class="error-msg">Error: ${esc(msg)}</p>`;
}
