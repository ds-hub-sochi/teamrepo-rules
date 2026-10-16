'use strict';
const data = JSON.parse(document.getElementById('audit-data').textContent);
const $ = id => document.getElementById(id);
const labels = {unknown:'Не установлено', unspecified:'Не определено', candidate:'Нужен разбор', reviewed:'Разобрано по коду', open_source:'Открытый код', open_weights:'Открытые веса', custom:'Модель проекта', fine_tuned:'Дообучение', proprietary_api:'API провайдера', documentation:'Документация', configuration:'Конфигурация', experiment:'Тест / эксперимент', training_code:'Код обучения', inference_code:'Код инференса', production_verified:'Проверенный runtime', scanned:'Прочитан заданный срез', partial:'Неполное чтение', empty:'Пустой', unavailable:'Недоступен', not_checked:'Не проверен', review_needed:'Нужна проверка', deprecated:'Deprecated', retired:'Выведена из эксплуатации', no_issue_found:'Проблем не найдено', found:'Модель найдена', related:'Найдена только возможная основа', code_only:'Компонент описан по коду', not_found:'Поиск без совпадений', pending:'Нужен разбор', analysed:'Бизнес-применение разобрано', exact:'Точное совпадение', alias:'Подтверждённый алиас', base_only:'Только номинальная основа', unresolved:'Точные веса не установлены'};
const label = x => labels[x] || x || 'Не установлено';
function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function link(text, url) {
  try {
    const u = new URL(url);
    if (u.protocol === 'https:' && !u.username && !u.password && !u.search) {
      const a = el('a', text); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a;
    }
  } catch {}
  return el('span', text);
}
function action(text, callback) {
  const b = el('button', text, 'linkbtn'); b.onclick = callback; return b;
}
function options(id, values) {
  for (const value of [...new Set(values.filter(Boolean))].sort()) {
    const option = el('option', label(value)); option.value = value; $(id).append(option);
  }
}
options('repo', data.repositories.map(r => r.repository));
options('domain', data.rows.map(r => r.business_domain));
options('origin', data.rows.map(r => r.origin));
$('meta').textContent = data.organization + ' · Снимок кода ' + new Date(data.generated_at).toLocaleString('ru-RU', {timeZone:'Europe/Moscow'}) + ' МСК · ' + (data.visibility === 'public' ? 'Публичный срез' : 'Внутренний срез');
const analysed = data.rows.filter(r => r.business_analysis === 'analysed').length;
$('scope').textContent = 'По коду разобрано ' + analysed + ' применений; ' + (data.rows.length - analysed) + ' находок ещё требуют разбора. Сбор охватывает ' + data.repositories.length + ' репозиториев. Ниже сначала показаны бизнес-задачи, а затем модели и основания выводов.';
$('method').textContent = 'Collector ' + data.collector_version + '. Default branch, до ' + data.coverage.max_files_per_repo + ' файлов и ' + data.coverage.max_bytes_per_file + ' байт на файл. Ответственный — владелец репозитория GitHub. Описание модели по model card не заменяет бизнес-задачу по коду.';
$('warnings').textContent = data.warnings.join('; ');
let current = [], page = 0;
const pageSize = 10;
function selected() {
  const query = $('search').value.toLowerCase();
  return data.rows.filter(r => {
    const info = r.model_info || {};
    return (!$('repo').value || r.repository === $('repo').value)
      && (!$('domain').value || r.business_domain === $('domain').value)
      && (!$('origin').value || r.origin === $('origin').value)
      && (!$('state').value || ($('state').value === 'analysed' ? r.business_analysis === 'analysed' : r.status === $('state').value))
      && (!query || [r.model, r.canonical_model, r.business_task, r.task, r.owner, r.repository, info.description].join(' ').toLowerCase().includes(query));
  });
}
function bars(id, counts, callback) {
  $(id).replaceChildren();
  const entries = Object.entries(counts).sort((a,b) => b[1] - a[1]);
  const maximum = Math.max(1, ...Object.values(counts));
  if (!entries.length) $(id).append(el('p', 'В выбранном срезе нет разобранных применений', 'empty'));
  for (const [name, value] of entries) {
    const row = el('div', undefined, 'bar-row');
    row.append(callback ? action(label(name), () => callback(name)) : el('span', label(name)));
    const track = el('div', undefined, 'bar-track'), bar = el('div', undefined, 'bar');
    bar.style.width = value / maximum * 100 + '%'; track.append(bar);
    row.append(track, el('span', String(value))); $(id).append(row);
  }
}
function detail(r) {
  $('detail-title').textContent = r.business_task || r.canonical_model || r.model;
  const body = $('detail-body'), info = r.model_info || {};
  body.replaceChildren();
  for (const [title, value] of [['Проект',r.repository],['Ответственный — владелец репозитория',r.owner],['Вход',r.input],['Результат',r.output],['Техническая роль',r.task],['Этап',label(r.stage)]]) body.append(el('p', title + ': ' + (value || 'Нужен разбор')));
  body.append(link('Владелец на GitHub', r.owner_evidence));
  body.append(el('h3', 'Что это за модель'));
  body.append(el('p', r.canonical_model || r.model));
  body.append(el('p', info.description || 'Описание самой модели ещё не исследовано'));
  for (const [title,value] of [['Результат поиска',label(info.lookup_status)],['Совпадение',label(info.match_status)],['Автор',info.publisher],['Архитектура',info.architecture],['Лицензия найденной модели',info.license],['Дата проверки',info.checked_at],['Базовая модель',r.base_model],['Версия используемых весов',r.revision]]) if (value) body.append(el('p',title + ': ' + value));
  if (info.source_url) body.append(link('Model card / официальный источник', info.source_url));
  if (info.readme_url) {const p=el('p');p.append(link('Версия model card на дату проверки',info.readme_url));body.append(p);}
  if (info.base_model_source) body.append(link('Model card базовой модели', info.base_model_source));
  for (const s of info.searches || []) body.append(el('p', 'Поиск: ' + s.query + ' · ' + (s.result || 'совпадений: ' + (s.results || []).length), 'small muted'));
  if (r.notes) body.append(el('p', r.notes, 'notice'));
  body.append(el('h3', 'Как это видно в коде'));
  for (const step of r.code_trace || []) {
    const p = el('p'); p.append(link(step.step, step.source)); body.append(p);
  }
  const evidence = el('details'); evidence.append(el('summary', 'Все свидетельства и SHA'));
  evidence.append(el('p', r.commit, 'small muted'));
  for (const e of r.evidence) {
    const p = el('p'); p.append(link(e.path + (e.cell ? ' · ' + e.cell : ':' + e.line), e.url)); evidence.append(p);
  }
  body.append(evidence);
  $('detail').showModal();
}
function renderFindings() {
  const findings = (data.findings || []).filter(f => !$('repo').value || f.repository === $('repo').value);
  $('findings-panel').hidden = !findings.length; $('findings').replaceChildren();
  for (const finding of findings) {
    const box = el('div', undefined, 'evidence');
    box.append(el('h3',finding.title),el('p',finding.repository),el('p',finding.reason),el('p','Следующий шаг: ' + finding.next_step),link('Первоисточник · ' + finding.checked_at,finding.source));
    for (const url of finding.code_evidence) {const p = el('p');p.append(link('Свидетельство в коде',url));box.append(p);}
    $('findings').append(box);
  }
}
function render() {
  current = selected();
  const done = current.filter(r => r.business_analysis === 'analysed');
  const owners = [...new Set(current.map(r => r.owner))];
  const stats = [['Разобранных применений',done.length,'Бизнес-задача прослежена по коду'],['Проектов в выборке',new Set(current.map(r => r.repository)).size,'Из ' + data.repositories.length + ' в исходном охвате'],['Модель исследована',done.filter(r => ['found','related','code_only'].includes(r.model_lookup)).length,'Точное совпадение и найденная основа различаются'],['Ответственный',owners.length === 1 ? owners[0] : owners.length,'Владелец репозитория GitHub']];
  $('stats').replaceChildren();
  for (const [title,value,note] of stats) {const box=el('div',undefined,'stat');box.append(el('div',title),el('span',String(value),'number'),el('small',note));$('stats').append(box);}
  const domains = {}, origins = {};
  for (const r of done) {domains[r.business_domain || 'Не определено']=(domains[r.business_domain || 'Не определено'] || 0)+1;origins[r.origin]=(origins[r.origin]||0)+1;}
  bars('families',domains,name=>{$('domain').value=name;page=0;render();}); bars('risks',origins);
  $('row-count').textContent = current.length;
  page = Math.min(page, Math.max(0, Math.ceil(current.length/pageSize)-1));
  $('page-label').textContent = 'Страница ' + (page+1) + ' из ' + Math.max(1,Math.ceil(current.length/pageSize));
  $('previous-page').disabled=page===0; $('next-page').disabled=(page+1)*pageSize>=current.length;
  $('usages').replaceChildren();
  for (const r of current.slice(page*pageSize,(page+1)*pageSize)) {
    const tr=el('tr'), goal=el('td'), model=el('td'), repo=el('td'), stage=el('td');
    goal.append(action(r.business_task || 'Бизнес-задача ещё не разобрана',()=>detail(r)));
    if (r.input) goal.append(el('p','Вход: ' + r.input,'small muted'));
    if (r.output) goal.append(el('p','Результат: ' + r.output,'small muted'));
    model.append(el('strong',r.canonical_model||r.model),el('p',(r.model_info||{}).description||'Нужен поиск модели','small'));
    if ((r.model_info||{}).source_url) model.append(link('Источник о модели',r.model_info.source_url));
    repo.append(el('div',r.repository),link(r.owner,r.owner_evidence));
    stage.append(el('span',label(r.stage),'badge'),el('p',label(r.model_lookup),'small muted'));
    tr.append(goal,model,repo,stage); $('usages').append(tr);
  }
  if (!current.length) {const tr=el('tr'),td=el('td','Нет записей по выбранным условиям','empty');td.colSpan=4;tr.append(td);$('usages').append(tr);}
  $('coverage').replaceChildren();
  for (const r of data.repositories.filter(r=>!$('repo').value||r.repository===$('repo').value)) {
    const tr=el('tr'),td=el('td');td.append(action(r.repository,()=>{$('repo').value=r.repository;$('search').value='';page=0;render();}));tr.append(td);
    for (const value of [label(r.scan_status),r.files_read+' / '+(r.candidates_total??'неизвестно'),r.usages.length,r.repository_owner||r.owner||r.repository.split('/')[0],(r.pushed_at||'').slice(0,10)]) tr.append(el('td',String(value)));
    if (r.errors.length || r.skipped.budget || r.skipped.oversize) tr.children[1].append(el('p','Ошибки: '+r.errors.length+'; вне бюджета: '+(r.skipped.budget||0)+'; крупные: '+(r.skipped.oversize||0),'small muted'));
    $('coverage').append(tr);
  }
  renderFindings(); $('changes-panel').hidden=!data.changes.length; $('changes').replaceChildren();
  for(const change of data.changes.filter(x=>!$('repo').value||x.repository===$('repo').value))$('changes').append(el('p',change.repository+' · '+(change.model||'')+' · '+change.change));
}
for (const id of ['search','repo','domain','state','origin']) $(id).addEventListener(id==='search'?'input':'change',()=>{page=0;render();});
$('previous-page').onclick=()=>{page--;render();}; $('next-page').onclick=()=>{page++;render();};
$('reset').onclick=()=>{for(const id of ['search','repo','domain','origin'])$(id).value='';$('state').value='analysed';page=0;render();};
$('close').onclick=()=>$('detail').close();
$('export').onclick=()=>{
  const blob=new Blob([JSON.stringify({generated_at:data.generated_at,filters:Object.fromEntries(['search','repo','domain','state','origin'].map(k=>[k,$(k).value])),rows:current},null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download='model-audit-selection.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
render();
