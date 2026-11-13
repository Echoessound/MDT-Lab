import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorState, Icon, Loading } from '../ui';
import { researchApi, type ModelConfiguration } from './api';
import { InlineError, roleNames } from './components';
import type { AgentModelStatus, ModelStatus, Role } from './schemas';
import { StorageStatus } from './storage-status';

export function selectedModelsReady(selected: Role[] | undefined, models: AgentModelStatus[] | undefined) {
  return !!selected?.length && selected.every(role => models?.some(item => item.agent_id === role && item.configured));
}

function ModelEditor({ status, role, onClose }: { status: ModelStatus; role?: Role; onClose?: () => void }) {
  const client = useQueryClient();
  const [form, setForm] = useState<ModelConfiguration>({ provider: status.provider, base_url: status.base_url, model: status.model, api_key: '', timeout_seconds: status.timeout_seconds, temperature: status.temperature, max_output_tokens: status.max_output_tokens });
  const [message, setMessage] = useState('');
  const invalidate = async () => {
    await Promise.all([client.invalidateQueries({ queryKey: ['research-model'] }), client.invalidateQueries({ queryKey: ['research-agent-models'] })]);
  };
  const save = useMutation({ mutationFn: () => role ? researchApi.configureAgent(role, form) : researchApi.configureModel(form), onSuccess: async () => { setForm(old => ({ ...old, api_key: '' })); setMessage('已保存，密钥已加密，密码输入已清空。'); await invalidate(); } });
  const clear = useMutation({ mutationFn: () => role ? researchApi.clearAgent(role) : researchApi.clearModel(), onSuccess: async value => { setForm({ provider: value.provider, base_url: value.base_url, model: value.model, api_key: '', timeout_seconds: value.timeout_seconds, temperature: value.temperature, max_output_tokens: value.max_output_tokens }); setMessage(role ? '已恢复继承默认配置。' : '已清除默认配置，独立 Agent 配置仍保留。'); await invalidate(); } });
  const test = useMutation({ mutationFn: () => role ? researchApi.testAgent(role) : researchApi.testModel(), onSuccess: value => setMessage(value.message) });
  const busy = save.isPending || clear.isPending || test.isPending;
  const ownsKey = role ? (status as AgentModelStatus).overridden : status.has_api_key;
  const update = (key: keyof ModelConfiguration, value: string | number) => { setMessage(''); setForm(old => ({ ...old, [key]: value })); };
  return <form className="research-form" onSubmit={event => { event.preventDefault(); setMessage(''); save.mutate(); }}>
    <label>Base URL<input type="url" autoComplete="off" required value={form.base_url} onChange={event => update('base_url', event.target.value)} placeholder="https://api.openai.com/v1" /></label>
    <label>Model<input autoComplete="off" required maxLength={160} value={form.model} onChange={event => update('model', event.target.value)} placeholder="服务提供方的模型标识" /></label>
    <label>API Key<input type="password" autoComplete="new-password" maxLength={1024} value={form.api_key} onChange={event => update('api_key', event.target.value)} placeholder={ownsKey ? '同地址可留空保留已有密钥' : '独立配置需要填写自己的密钥'} /></label>
    <div className="research-form-row"><label>单次超时 / 秒<input type="number" required min={1} max={60} value={form.timeout_seconds} onChange={event => update('timeout_seconds', Number(event.target.value))} /></label><label>Temperature<input type="number" required min={0} max={2} step={0.1} value={form.temperature} onChange={event => update('temperature', Number(event.target.value))} /></label></div>
    <label>最大输出 Token<input type="number" required min={128} max={8192} value={form.max_output_tokens} onChange={event => update('max_output_tokens', Number(event.target.value))} /></label>
    <InlineError error={save.error || clear.error || test.error} />{message && <p className="notice neutral" role="status">{message}</p>}
    <div className="button-group"><button className="button primary" disabled={busy}>{save.isPending ? '正在保存…' : role ? '保存独立配置' : '保存默认配置'}</button><button type="button" className="button secondary" disabled={!status.configured || busy} onClick={() => { setMessage(''); test.mutate(); }}>{test.isPending ? '正在测试…' : '测试已保存配置'}</button></div>
    <div className="button-group"><button type="button" className="text-link" disabled={!ownsKey || busy} onClick={() => clear.mutate()}>{role ? '恢复继承默认' : '清除默认配置'}</button>{onClose && <button type="button" className="text-link" onClick={onClose}>收起设置</button>}</div>
  </form>;
}

export function AgentModelCard({ item }: { item: AgentModelStatus }) {
  const [editing, setEditing] = useState(false);
  return <article className="panel agent-model-card">
    <div className="section-heading"><div><span className="eyebrow">{item.agent_id.toUpperCase()}</span><h3>{roleNames[item.agent_id]}</h3></div><span className={`pill ${item.configured ? 'soft' : 'outline'}`}>{item.overridden ? '独立配置' : item.configured ? '继承默认' : '未配置'}</span></div>
    <p className="model-name">{item.model || 'Mock 可用 · LLM 待配置'}</p><p className="model-endpoint">{item.configured ? item.base_url : '可为此专科指定模型服务和独立密钥。'}</p>
    <button className="text-link" aria-expanded={editing} onClick={() => setEditing(value => !value)}><Icon name="settings" size={14} />{editing ? '收起配置' : `配置${roleNames[item.agent_id]}`}</button>
    {editing && <ModelEditor status={item} role={item.agent_id} onClose={() => setEditing(false)} />}
  </article>;
}

export function AgentSettingsGrid() {
  const query = useQuery({ queryKey: ['research-agent-models'], queryFn: researchApi.agentModels });
  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} retry={() => void query.refetch()} />;
  return <div className="agent-settings-grid">{query.data.map(item => <AgentModelCard item={item} key={item.agent_id} />)}</div>;
}

export function ModelSettingsPage() {
  const query = useQuery({ queryKey: ['research-model'], queryFn: researchApi.modelStatus });
  return <div className="page-enter research-page"><div className="page-heading"><div><span className="eyebrow">MODEL CONNECTIONS / PER-AGENT CONTROL</span><h1>每个专科，独立配置<span className="title-period">.</span></h1><p>统一默认连接，也可为每个 Agent 指定 URL、模型、密钥和生成参数。</p></div></div>
    <div className="research-stack"><StorageStatus /><AgentSettingsGrid />
      <div className="research-settings-grid"><section className="panel"><h2>共享默认配置</h2><p className="muted">没有独立配置的 Agent 会继承这里的连接。</p>{query.isPending ? <Loading /> : query.isError ? <InlineError error={query.error} /> : <ModelEditor status={query.data} />}</section>
        <aside className="panel"><h2>配置如何生效</h2><ol className="settings-notes"><li>独立配置优先；恢复继承后使用共享默认连接。</li><li>启动时冻结本次参与 Agent 的配置。后续修改只影响新运行。</li><li>密钥加密保存，页面、报告与审计只显示模型和参数。重启后可恢复配置。</li><li>更换 URL 必须重新填写密钥。服务需支持 Chat Completions 与严格 JSON Schema。</li><li>“测试已保存配置”会发送一条不含病例的短请求，可能产生少量费用。</li></ol><p className="subtle-note">当前应用供本机使用。模型服务使用公网 HTTPS；独立配置不会复制其他 Agent 的密钥。</p></aside></div>
    </div></div>;
}
