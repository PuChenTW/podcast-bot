import { renderHome } from './home.js';
import { renderEpisodeList, renderEpisodeDetail } from './episodes.js';

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
