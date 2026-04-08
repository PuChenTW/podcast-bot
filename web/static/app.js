const savedTheme = localStorage.getItem('theme') ?? 'light';
document.documentElement.dataset.theme = savedTheme;

document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('theme-toggle');
    btn.textContent = savedTheme === 'dark' ? '☀️' : '🌙';
    btn.addEventListener('click', () => {
        const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
        document.documentElement.dataset.theme = next;
        localStorage.setItem('theme', next);
        btn.textContent = next === 'dark' ? '☀️' : '🌙';
    });
});

import './modules/router.js';
