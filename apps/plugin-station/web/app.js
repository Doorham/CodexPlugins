const state = { dashboard: null, page: 'shared', filter: '全部', busy: new Set(), domainPlugin: null, domains: [] };
const grid = document.getElementById('pluginGrid');

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
}

function showToast(message, error = false) {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.className = `toast show${error ? ' error' : ''}`;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.className = 'toast', 2600);
}

function renderFilters(plugins) {
  const values = ['全部', ...new Set(plugins.map(p => p.category))];
  document.getElementById('filters').innerHTML = values.map(value =>
    `<button class="filter ${state.filter === value ? 'active' : ''}" data-filter="${escapeHtml(value)}">${escapeHtml(value)}</button>`
  ).join('');
  document.querySelectorAll('.filter').forEach(button => button.onclick = () => {
    state.filter = button.dataset.filter;
    render();
  });
}

function renderPageTabs() {
  document.querySelectorAll('.page-tab').forEach(button => {
    button.classList.toggle('active', button.dataset.page === state.page);
    button.setAttribute('aria-selected', String(button.dataset.page === state.page));
  });
  document.getElementById('privateNotice').hidden = state.page !== 'private';
  const errors = state.dashboard.privateLayer.errors || [];
  document.getElementById('privateLayerStatus').textContent = errors.length
    ? `有 ${errors.length} 个私人清单未通过安全检查；公共插件不受影响。`
    : '私人插件默认不上传 Y 盘、不进入 Git、不同步到其他员工电脑。';
}

function card(plugin) {
  const actions = plugin.actions.map(action => {
    const key = `${plugin.id}:${action.id}`;
    const toggle = action.kind === 'toggle';
    const label = toggle ? (plugin.enabled ? '点我停用' : '点我开启') : action.label;
    const statusDisabled = Boolean(action.disabled);
    const kind = `${toggle ? `toggle ${plugin.enabled ? 'enabled' : 'disabled'}` : action.kind}${statusDisabled ? ' status-disabled' : ''}`;
    const disabled = statusDisabled || state.busy.has(key);
    return `<button class="action ${escapeHtml(kind)}" data-plugin="${escapeHtml(plugin.id)}" data-action="${escapeHtml(action.id)}"
      data-dialog="${escapeHtml(action.dialog || '')}" ${disabled ? 'disabled' : ''}>${escapeHtml(label)}</button>`;
  }).join('');
  const metric = plugin.metric ? `<div class="card-metric ${escapeHtml(plugin.metric.state)}">
    <strong>${escapeHtml(plugin.metric.value)}</strong><span>${escapeHtml(plugin.metric.label)}</span>
  </div>` : '';
  return `<article class="card ${plugin.metric ? 'has-metric' : ''}" style="--accent:${escapeHtml(plugin.accent)}">
    <div class="card-head">
      <div class="plugin-icon">${escapeHtml(plugin.icon)}</div>
      <div class="status"><span class="status-dot ${plugin.running ? 'on' : ''}"></span>${escapeHtml(plugin.statusText)}</div>
    </div>
    <h3>${escapeHtml(plugin.name)}</h3>
    <div class="module-meta">
      <span class="category">${escapeHtml(plugin.category)}</span>
      <span class="developer">v${escapeHtml(plugin.moduleVersion)} · ${escapeHtml(plugin.developers.join(' / '))}</span>
    </div>
    <p class="description">${escapeHtml(plugin.description)}</p>
    <div class="details">${plugin.detailLines.map(line => `<span>${escapeHtml(line)}</span>`).join('')}</div>
    <div class="actions">${actions}</div>
    ${metric}
  </article>`;
}

function render() {
  if (!state.dashboard) return;
  renderPageTabs();
  const plugins = state.dashboard.plugins.filter(plugin => plugin.scope === state.page);
  renderFilters(plugins);
  document.getElementById('version').textContent = `v${state.dashboard.app.version} · ${state.dashboard.app.developers.map(escapeHtml).join(' / ')}`;
  document.getElementById('summary').textContent = `${state.page === 'private' ? '私人' : '公共'} · ${plugins.filter(p => p.enabled || p.running).length} 个开启 · ${plugins.length} 个插件`;
  const visible = state.filter === '全部' ? plugins : plugins.filter(p => p.category === state.filter);
  grid.innerHTML = visible.length ? visible.map(card).join('') : `<div class="empty-page">
    <strong>${state.page === 'private' ? '还没有私人插件' : '当前分类没有插件'}</strong>
    <span>${state.page === 'private' ? '让本地 Agent 在私人插件目录创建模块即可；这些内容不会上传或同步。' : '请选择其他分类。'}</span>
  </div>`;
  grid.querySelectorAll('.action').forEach(button => button.onclick = () => runAction(button));
}

async function refresh(silent = false) {
  try {
    state.dashboard = await window.pywebview.api.get_dashboard();
    document.getElementById('lastUpdated').textContent = `本机状态 · ${new Date().toLocaleTimeString('zh-CN', {hour12:false})}`;
    render();
  } catch (error) {
    if (!silent) showToast(`读取失败：${error}`, true);
  }
}

async function runAction(button) {
  const pluginId = button.dataset.plugin;
  const action = button.dataset.action;
  if (button.dataset.dialog === 'domain') {
    state.domainPlugin = pluginId;
    await openDomainModal();
    return;
  }
  if (action === 'test_sound') {
    try {
      const result = await window.pywebview.api.perform_action(pluginId, action, {});
      showToast(result.message, !result.ok);
    } catch (error) {
      showToast(`播放失败：${error}`, true);
    }
    return;
  }
  const busyKey = `${pluginId}:${action}`;
  if (button.dataset.dialog === 'sound') {
    state.busy.add(busyKey); render();
    try {
      const result = await window.pywebview.api.choose_sound_file();
      if (!result.cancelled) showToast(result.message, !result.ok);
    } catch (error) {
      showToast(`选择失败：${error}`, true);
    } finally {
      state.busy.delete(busyKey);
      await refresh(true);
    }
    return;
  }
  state.busy.add(busyKey); render();
  try {
    const result = await window.pywebview.api.perform_action(pluginId, action, {});
    showToast(result.message, !result.ok);
  } catch (error) {
    showToast(`操作失败：${error}`, true);
  } finally {
    state.busy.delete(busyKey);
    await refresh(true);
  }
}

async function openDomainModal() {
  const modal = document.getElementById('domainModal');
  const input = document.getElementById('domainInput');
  input.value = '';
  setDomainFeedback('正在读取白名单…');
  document.getElementById('domainList').innerHTML = '<div class="domain-empty">正在读取…</div>';
  modal.classList.add('show');
  modal.setAttribute('aria-hidden', 'false');
  await loadDomains();
  setTimeout(() => input.focus(), 50);
}

function closeDomainModal() {
  const modal = document.getElementById('domainModal');
  modal.classList.remove('show');
  modal.setAttribute('aria-hidden', 'true');
  state.domainPlugin = null;
}

function setDomainFeedback(message, error = false) {
  const feedback = document.getElementById('domainFeedback');
  feedback.textContent = message || '';
  feedback.className = `domain-feedback${error ? ' error' : ''}`;
}

function renderDomains() {
  const list = document.getElementById('domainList');
  if (!state.domains.length) {
    list.innerHTML = '<div class="domain-empty">尚未读取到白名单主站</div>';
    return;
  }
  list.innerHTML = state.domains.map(item => `
    <div class="domain-row">
      <div class="domain-name">
        <strong>${escapeHtml(item.domain)}</strong>
        <span class="domain-source ${item.deletable ? 'custom' : ''}">${escapeHtml(item.source)}</span>
        <small>${item.activeCount === 2 ? '主站和子域均生效' : `当前生效 ${escapeHtml(item.activeCount)}/2`}</small>
      </div>
      ${item.deletable ? `<button class="domain-delete" data-domain="${escapeHtml(item.domain)}">删除</button>` : ''}
    </div>`).join('');
  list.querySelectorAll('.domain-delete').forEach(button => {
    button.onclick = () => deleteDomain(button.dataset.domain, button);
  });
}

async function loadDomains(showSummary = true) {
  try {
    const result = await window.pywebview.api.perform_action(state.domainPlugin, 'list_domains', {});
    if (!result.ok) throw new Error(result.message);
    state.domains = result.domains || [];
    renderDomains();
    if (showSummary) setDomainFeedback(`共 ${state.domains.length} 个主站；内置规则只读，自定义规则可以删除。`);
  } catch (error) {
    setDomainFeedback(`读取失败：${error}`, true);
    document.getElementById('domainList').innerHTML = '<div class="domain-empty">读取失败</div>';
  }
}

async function saveDomain() {
  const domain = document.getElementById('domainInput').value.trim();
  if (!domain) {
    setDomainFeedback('请输入主站域名，例如 example.com', true);
    return;
  }
  const pluginId = state.domainPlugin;
  const saveButton = document.getElementById('saveDomain');
  saveButton.disabled = true;
  setDomainFeedback('正在写入并刷新 WinINet…');
  try {
    const result = await window.pywebview.api.perform_action(pluginId, 'add_domain', {domain});
    showToast(result.message, !result.ok);
    if (result.ok) document.getElementById('domainInput').value = '';
    await loadDomains(false);
    setDomainFeedback(result.message, !result.ok);
  } catch (error) {
    setDomainFeedback(`添加失败：${error}`, true);
  } finally {
    saveButton.disabled = false;
    await refresh(true);
  }
}

async function deleteDomain(domain, button) {
  button.disabled = true;
  setDomainFeedback(`正在删除 ${domain}…`);
  try {
    const result = await window.pywebview.api.perform_action(state.domainPlugin, 'delete_domain', {domain});
    showToast(result.message, !result.ok);
    await loadDomains(false);
    setDomainFeedback(result.message, !result.ok);
  } catch (error) {
    setDomainFeedback(`删除失败：${error}`, true);
  } finally {
    await refresh(true);
  }
}

document.getElementById('refreshButton').onclick = () => refresh();
document.getElementById('updateButton').onclick = async () => {
  const button = document.getElementById('updateButton');
  button.disabled = true;
  button.textContent = '检查中…';
  let restarting = false;
  try {
    const result = await window.pywebview.api.update_toolbox();
    if (!result.ok) {
      showToast(result.message || '更新失败', true);
      return;
    }
    if (!result.updated) {
      showToast(result.message || '当前已是最新版');
      return;
    }
    restarting = true;
    button.textContent = '正在重启…';
    showToast(result.message || '更新完成，正在重启');
    setTimeout(() => window.pywebview.api.restart_after_update(), 450);
  } catch (error) {
    showToast(`更新失败：${error}`, true);
  } finally {
    if (!restarting) {
      button.disabled = false;
      button.textContent = '检查更新';
    }
  }
};
document.querySelectorAll('.page-tab').forEach(button => button.onclick = () => {
  state.page = button.dataset.page;
  state.filter = '全部';
  render();
});
document.getElementById('openPrivateFolder').onclick = async () => {
  try {
    const result = await window.pywebview.api.open_private_plugins_folder();
    showToast(result.message, !result.ok);
  } catch (error) {
    showToast(`打开失败：${error}`, true);
  }
};
document.getElementById('cancelDomain').onclick = closeDomainModal;
document.getElementById('saveDomain').onclick = saveDomain;
document.getElementById('domainInput').onkeydown = event => {
  if (event.key === 'Enter') saveDomain();
  if (event.key === 'Escape') closeDomainModal();
};
document.getElementById('domainModal').onclick = event => {
  if (event.target.id === 'domainModal') closeDomainModal();
};
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && document.getElementById('domainModal').classList.contains('show')) closeDomainModal();
});
document.querySelectorAll('[data-window]').forEach(button => button.onclick = () =>
  window.pywebview.api.window_action(button.dataset.window)
);
setInterval(() => {
  document.getElementById('clock').textContent = new Date().toLocaleTimeString('zh-CN', {hour12:false, hour:'2-digit', minute:'2-digit'});
}, 1000);

window.addEventListener('pywebviewready', () => {
  refresh();
  setInterval(() => refresh(true), 5000);
});
