import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Icon } from '../ui';
import { researchApi } from './api';
import { InlineError, roleNames } from './components';
import { configurationFrom, ConnectionFields, draftFrom, sameDraft, type ConnectionDraft } from './model-connection-fields';
import type { AgentModelStatus, ModelProfile, ModelStatus, Role } from './schemas';

export type ModelScope = Role | 'default';
export function scopeName(scope: ModelScope) { return scope === 'default' ? '共享默认' : roleNames[scope]; }

type ProfileDraft = { name: string; connection: ConnectionDraft };
type ScopePrompt = { scope: ModelScope; target?: ModelProfile; name: string; archived?: string };
type ProfileAction =
  | { kind: 'save'; id: string; value: ProfileDraft; provider?: string }
  | { kind: 'test' | 'delete' | 'activate'; profile: ModelProfile }
  | { kind: 'archive'; name: string };

export function ModelProfiles({ scope, status, shared, agents, dirtyConnection, busy, onBusy }: {
  scope: ModelScope; status: ModelStatus; shared: ModelStatus; agents: AgentModelStatus[];
  dirtyConnection: boolean; busy: boolean; onBusy: (busy: boolean) => void;
}) {
  const client = useQueryClient();
  const profiles = useQuery({ queryKey: ['model-profiles'], queryFn: researchApi.modelProfiles });
  // An empty ID is the draft of a new, unnamed connection. Draft secrets live only in page memory.
  const [editing, setEditing] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, ProfileDraft>>({});
  const [deleting, setDeleting] = useState<string | null>(null);
  const [prompt, setPrompt] = useState<ScopePrompt | null>(null);
  const [message, setMessage] = useState('');
  const source = profiles.data?.find(p => p.profile_id === editing);
  const original = { name: source?.name ?? '', connection: draftFrom(source) };
  const form = (editing !== null && drafts[editing]) || original;
  const dirty = form.name !== original.name || !sameDraft(form.connection, original.connection);
  const local = scope === 'default' || ('overridden' in status && !!status.overridden);
  const direct = status.configured && !status.profile_id;
  const bindings = (id: string) => [
    ...(shared.profile_id === id ? ['共享默认'] : []),
    ...agents.filter(item => item.overridden && item.profile_id === id).map(item => roleNames[item.agent_id]),
  ];
  const dropDraft = (id: string) => setDrafts(old => {
    const next = { ...old }; delete next[id]; return next;
  });

  const action = useMutation({
    mutationFn: async (request: ProfileAction) => {
      if (request.kind === 'test') {
        const result = await researchApi.testModelProfile(request.profile.profile_id);
        return request.profile.name + ' · ' + result.message;
      }
      let feedback: string;
      if (request.kind === 'archive') {
        const saved = await researchApi.saveScopeAsModelProfile(scope, request.name.trim());
        setPrompt(old => old?.target ? { ...old, archived: saved.name } : null);
        feedback = '已将' + scopeName(scope) + '的原连接存为「' + saved.name + '」。';
      } else if (request.kind === 'save') {
        const value = { name: request.value.name.trim(), ...configurationFrom(request.value.connection, request.provider) };
        const saved = request.id ? await researchApi.updateModelProfile(request.id, value)
          : await researchApi.createModelProfile(value);
        dropDraft(request.id);
        setEditing(null);
        feedback = request.id ? '方案「' + saved.name + '」已更新。' : '已创建「' + saved.name + '」，可选择使用范围后启用。';
      } else if (request.kind === 'delete') {
        await researchApi.deleteModelProfile(request.profile.profile_id);
        dropDraft(request.profile.profile_id);
        if (editing === request.profile.profile_id) setEditing(null);
        setDeleting(null);
        feedback = '已删除「' + request.profile.name + '」。';
      } else {
        await researchApi.activateModelProfile(request.profile.profile_id, scope);
        setPrompt(null);
        feedback = scopeName(scope) + '已启用「' + request.profile.name + '」。' +
          (dirtyConnection ? '直接配置的未保存草稿已保留。' : '');
      }
      await Promise.all([
        client.invalidateQueries({ queryKey: ['model-profiles'] }),
        client.invalidateQueries({ queryKey: ['research-model'] }),
        client.invalidateQueries({ queryKey: ['research-agent-models'] }),
      ]);
      return feedback;
    },
    onSuccess: setMessage,
    onSettled: () => onBusy(false),
  });

  function clearFeedback() { setMessage(''); action.reset(); }
  function perform(request: ProfileAction) {
    clearFeedback();
    onBusy(true);
    action.mutate(request);
  }
  function openEditor(id: string) {
    clearFeedback(); setDeleting(null); setPrompt(null); setEditing(id);
  }
  function archivePrompt(target?: ModelProfile) {
    clearFeedback(); setDeleting(null); setEditing(null);
    const name = `${scopeName(scope)} · ${status.model}`.slice(0, 80);
    setPrompt({ scope, target, name });
  }
  function beginSwitch(profile: ModelProfile) {
    if (direct && local) archivePrompt(profile);
    else perform({ kind: 'activate', profile });
  }
  function edit(value: ProfileDraft) {
    if (editing !== null) setDrafts(old => ({ ...old, [editing]: value }));
    clearFeedback();
  }
  const openPrompt = prompt?.scope === scope ? prompt : null;
  return <section className="panel model-editor model-profiles" aria-labelledby="model-profiles-heading">
    <div className="model-section-heading">
      <h2 id="model-profiles-heading">连接方案</h2>
      <div className="model-profile-actions">
        {direct && <button type="button" className="text-link" disabled={busy} onClick={() => archivePrompt()}>将当前连接存为方案</button>}
        <button type="button" className="button secondary" disabled={busy} onClick={() => openEditor('')}>
          {drafts[''] ? '继续新建方案' : '新建方案'}</button>
      </div>
    </div>
    <p className="model-context">选择用于{scopeName(scope)}的连接。启用后的参数用于下次新建运行。</p>

    {openPrompt && <form className="research-form profile-edit-form" aria-label="保存原连接" onSubmit={event => {
      event.preventDefault();
      if (!busy && !openPrompt.archived) perform({ kind: 'archive', name: openPrompt.name });
    }}>
      <h3>{openPrompt.target ? '切换到「' + openPrompt.target.name + '」' : '保存当前连接'}</h3>
      {openPrompt.target && <p className="model-context">启用方案会替换{scopeName(scope)}已保存的直接配置。可先归档原连接和密钥，方便切回。</p>}
      {!openPrompt.archived && <label>原连接的方案名称<input required maxLength={80} disabled={busy} value={openPrompt.name}
        onChange={event => setPrompt({ ...openPrompt, name: event.target.value })} /></label>}
      <div className="model-editor-actions">
        {!openPrompt.archived && <button type="submit" className="button secondary" disabled={busy || !openPrompt.name.trim()}>
          {openPrompt.target ? '先存为方案' : '保存当前连接'}</button>}
        {openPrompt.target && <button type="button" className="button primary" disabled={busy}
          onClick={() => perform({ kind: 'activate', profile: openPrompt.target! })}>{openPrompt.archived ? '启用目标方案' : '直接切换'}</button>}
        <button type="button" className="text-link" disabled={busy} onClick={() => { setPrompt(null); clearFeedback(); }}>取消</button>
      </div>
    </form>}

    {editing !== null && (editing === '' || source) && <form className="research-form profile-edit-form"
      aria-label={source ? '编辑连接方案' : '新建连接方案'} onSubmit={event => {
        event.preventDefault();
        if (!busy && dirty) perform({ kind: 'save', id: editing, value: form, provider: source?.provider });
      }}>
      <h3>{source ? '编辑「' + source.name + '」' : '新建连接方案'}</h3>
      {source && bindings(source.profile_id).length > 0 &&
        <p className="model-context">保存后，使用此方案的范围将在新运行中采用更新后的参数。</p>}
      <label>方案名称<input required maxLength={80} value={form.name} disabled={busy}
        onChange={event => edit({ ...form, name: event.target.value })} /></label>
      <ConnectionFields form={form.connection} savedKeyUrl={source?.has_api_key ? source.base_url : undefined}
        disabled={busy} onChange={(key, value) => edit({ ...form, connection: { ...form.connection, [key]: value } })} />
      <div className="model-editor-actions">
        <button type="submit" className="button primary" disabled={busy || !dirty || !form.name.trim()}>保存方案</button>
        <button type="button" className="text-link" disabled={busy} onClick={() => { setEditing(null); clearFeedback(); }}>
          {dirty ? '收起并保留草稿' : '收起'}</button>
        {dirty && <button type="button" className="text-link model-clear" disabled={busy}
          onClick={() => { dropDraft(editing); setEditing(null); clearFeedback(); }}>放弃草稿</button>}
      </div>
    </form>}

    {profiles.isError ? <div className="model-profile-error"><InlineError error={profiles.error} />
      <button type="button" className="text-link" onClick={() => void profiles.refetch()}>重试加载方案</button></div>
      : profiles.isPending ? <p className="model-context" role="status">正在读取方案…</p>
      : !profiles.data.length ? <p className="model-profile-empty">暂无已保存方案，可新建方案或保存已有连接。</p>
      : <ul className="model-profile-list">{profiles.data.map(profile => {
        const active = status.profile_id === profile.profile_id;
        const bound = active && local;
        const usedBy = bindings(profile.profile_id);
        return <li key={profile.profile_id} className="model-profile-card" data-active={active}>
          <div className="model-profile-title"><h3>{profile.name}</h3>
            {active && <span className="pill soft"><Icon name="check" size={13} />{bound ? '使用中' : '继承使用中'}</span>}
            {drafts[profile.profile_id] && <small className="draft-marker">有编辑草稿</small>}</div>
          <p className="model-profile-connection"><strong>{profile.model}</strong><span>{profile.base_url}</span></p>
          {usedBy.length > 0 && <p className="model-context">已绑定到{usedBy.join('、')}</p>}
          <div className="model-profile-actions">
            <button type="button" className="button secondary" disabled={busy || bound}
              onClick={() => beginSwitch(profile)}>{bound ? '已启用' : active ? '独立绑定到' + scopeName(scope) : '启用于' + scopeName(scope)}</button>
            <button type="button" className="text-link" disabled={busy}
              onClick={() => perform({ kind: 'test', profile })}>测试方案</button>
            <button type="button" className="text-link" disabled={busy}
              onClick={() => openEditor(profile.profile_id)}>{drafts[profile.profile_id] ? '继续编辑' : '编辑'}</button>
            <button type="button" className="text-link model-clear" disabled={busy || usedBy.length > 0}
              title={usedBy.length ? '先将所有绑定范围切换到其他连接' : undefined}
              onClick={() => { clearFeedback(); setDeleting(profile.profile_id); setPrompt(null); }}>删除</button>
          </div>
          {deleting === profile.profile_id && <div className="model-clear-prompt">
            <p>删除「{profile.name}」及其密钥{drafts[profile.profile_id] ? '和编辑草稿' : ''}？</p>
            <button type="button" className="button secondary" disabled={busy}
              onClick={() => perform({ kind: 'delete', profile })}>确认删除方案</button>
            <button type="button" className="text-link" disabled={busy} onClick={() => setDeleting(null)}>取消</button>
          </div>}
        </li>;
      })}</ul>}
    {profiles.data?.length ? <p className="model-help">测试方案会向该方案的服务发送一条短请求，可能产生费用。</p> : null}
    <InlineError error={action.error} />
    {message && <p className="model-feedback" role="status"><Icon name="check" size={15} />{message}</p>}
  </section>;
}
