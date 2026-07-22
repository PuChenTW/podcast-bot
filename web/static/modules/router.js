import { renderHome } from './home.js';
import { renderEpisodeList, renderEpisodeDetail } from './episodes.js';

function route() {
    const hash = location.hash || '#/';
    const content = document.getElementById('content');
    content.innerHTML = '';

    if (hash === '#/' || hash === '') {
        renderHome(content);
    } else if (hash.startsWith('#/podcast/')) {
        const [podcastId, query = ''] = hash.slice('#/podcast/'.length).split('?');
        const params = new URLSearchParams(query);
        renderEpisodeList(content, podcastId, params.get('cursor'), parseInt(params.get('page') || '0', 10));
    } else if (hash.startsWith('#/episode/')) {
        const episodeId = hash.slice('#/episode/'.length);
        renderEpisodeDetail(content, episodeId);
    } else {
        content.innerHTML = '<p>Page not found.</p>';
    }
}

window.addEventListener('hashchange', route);
window.addEventListener('load', route);
