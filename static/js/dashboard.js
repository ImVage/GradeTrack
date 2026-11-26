function switchTab(tabName) {
  document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.nav-pills a').forEach(el => el.classList.remove('active'));
  const pane = document.getElementById('tab-' + tabName);
  const link = document.querySelector('.nav-pills a[data-tab="' + tabName + '"]');
  if (pane) pane.classList.add('active');
  if (link) link.classList.add('active');
  const url = new URL(window.location);
  url.searchParams.set('tab', tabName);
  window.history.replaceState({}, '', url);
}

function syncModule(sel) {
  const opt = sel.options[sel.selectedIndex];
  if (!opt) return;
  document.getElementById('ectsInput').value = opt.dataset.ects || 5;
  document.getElementById('semInput').value = opt.dataset.sem || 1;
}

document.querySelectorAll('.nav-pills a[data-tab]').forEach(link => {
  link.addEventListener('click', () => switchTab(link.dataset.tab));
});

document.querySelectorAll('[data-switch-tab]').forEach(button => {
  button.addEventListener('click', () => switchTab(button.dataset.switchTab));
});

const moduleSelect = document.getElementById('moduleSelect');
if (moduleSelect) {
  moduleSelect.addEventListener('change', () => syncModule(moduleSelect));
}

document.querySelectorAll('.progress-fill[data-width]').forEach(bar => {
  bar.style.width = bar.dataset.width + '%';
});
