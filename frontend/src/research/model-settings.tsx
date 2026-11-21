import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { ErrorState, Icon, Loading } from '../ui';
import { researchApi, type ModelConfiguration } from './api';
import { InlineError, roleNames } from './components';
import { roleSchema, type AgentModelStatus, type ModelStatus, type Role } from './schemas';
import { StorageStatus } from './storage-status';
import './agent-console.css';

export function selectedModelsReady(selected: Role[] | undefined, models: AgentModelStatus[] | undefined) {
  return !!selected?.length && selected.every(role => models?.some(item => item.agent_id === role && item.configured));
}

type Scope = Role | 'default';
type ConnectionDraft = {
  url: string; model: string; key: string;
  timeout: string; temperature: string; tokens: string;
};

function draftFrom(status: ModelStatus): ConnectionDraft {
  return {
    url: status.base_url, model: status.model, key: '',
    timeout: String(status.timeout_seconds), temperature: String(status.temperature), tokens: String(status.max_output_tokens),
  };
}

function scopeName(scope: Scope) {
  return scope === 'default' ? '共享默认' : roleNames[scope];
}

function sourceName(status: ModelStatus, scope: Scope) {
  if (!status.configured) return '未配置';
  if (scope === 'default') return '已配置';
  return 'overridden' in status && status.overridden ? '独立配置' : '继承默认';
}

function sameDraft(a: ConnectionDraft, b: ConnectionDraft) {
  return (Object.keys(a) as (keyof ConnectionDraft)[]).every(key => a[key] === b[key]);
}

export function ModelSettingsPage() {
  const shared = useQuery({ queryKey: ['research-model'], queryFn: researchApi.modelStatus });
  const agents = useQuery({ queryKey: ['research-agent-models'], queryFn: researchApi.agentModels });
  const [params, setParams] = useSearchParams();
  const requested = roleSchema.safeParse(params.get('agent'));
  const scope: Scope = requested.success ? requested.data : 'default';
  // Drafts stay in component memory so switching specialists does not discard edits.
  const [drafts, setDrafts] = useState<Partial<Record<Scope, ConnectionDraft>>>({});
  const [busy, setBusy] = useState(false);
  const status = scope === 'default' ? shared.data : agents.data?.find(item => item.agent_id === scope);

  const selectScope = (value: Scope) => setParams(next => {
    if (value === 'default') next.delete('agent');
    else next.set('agent', value);
    return next;
  });
  const updateDraft = (draft?: ConnectionDraft) => setDrafts(old => {
    const next = { ...old };
    if (draft) next[scope] = draft;
    else delete next[scope];
    return next;
  });

  return <div className="page-enter research-page agent-console">
    <header className="page-heading">
      <div>
        <h1>专科大模型连接设置</h1>
        <p>管理全局默认连接或为各专科独立指派异构大模型服务，所有密钥经本地加密持久化</p>
      </div>
      <Link className="button secondary" to="/research/agents"><Icon name="network" size={15} />多智能体协同</Link>
    </header>
    {shared.isPending || agents.isPending ? <Loading /> : shared.isError || agents.isError ?
      <ErrorState error={shared.error ?? agents.error} retry={() => { void shared.refetch(); void agents.refetch(); }} /> :
      <div className="model-workspace">
        <section className="panel model-roster" aria-label="模型连接列表">
          <div className="model-section-heading"><h2>连接列表</h2></div>
          {[{ scope: 'default' as Scope, status: shared.data }, ...agents.data.map(agent => ({ scope: agent.agent_id, status: agent }))].map(item => (
            <button key={item.scope} type="button" aria-pressed={item.scope === scope} disabled={busy && item.scope !== scope}
              onClick={() => selectScope(item.scope)} className="model-connection">
              <span className="model-connection-name"><strong>{scopeName(item.scope)}</strong>
                {drafts[item.scope] && <small className="draft-marker">未保存</small>}
              </span>
              <span className="model-summary">{item.status.model || '—'}<span>{sourceName(item.status, item.scope)}</span></span>
            </button>
          ))}
        </section>
        {status && <ConnectionEditor key={scope} scope={scope} status={status} draft={drafts[scope]}
          onDraft={updateDraft} onBusy={setBusy} />}
      </div>}
    <StorageStatus />
  </div>;
}

type EditorProps = {
  scope: Scope; status: ModelStatus; draft?: ConnectionDraft;
  onDraft: (draft?: ConnectionDraft) => void; onBusy: (value: boolean) => void;
};

function ConnectionEditor({ scope, status, draft, onDraft, onBusy }: EditorProps) {
  const client = useQueryClient();
  const [message, setMessage] = useState('');
  const [confirmClear, setConfirmClear] = useState(false);
  const current = draftFrom(status);
  const form = draft ?? current;
  const dirty = !sameDraft(current, form);
  const role = scope === 'default' ? undefined : scope;
  const own = role ? 'overridden' in status && !!status.overridden : status.has_api_key;
  const hasKey = own && status.has_api_key;
  const normalizeUrl = (url: string) => url.trim().replace(/\/+$/, '');
  const needKey = !hasKey || normalizeUrl(form.url) !== normalizeUrl(status.base_url);
  const record = async (value: ModelStatus | AgentModelStatus) => {
    if (role) {
      client.setQueryData<AgentModelStatus[]>(['research-agent-models'], old =>
        old?.map(item => item.agent_id === role ? value as AgentModelStatus : item));
    } else {
      client.setQueryData(['research-model'], value);
    }
    onDraft();
    await client.invalidateQueries({ queryKey: ['research-agent-models'] });
  };
  const operation = useMutation({
    mutationFn: async (action: 'save' | 'test' | 'clear') => {
      if (action === 'test') {
        const result = role ? await researchApi.testAgent(role) : await researchApi.testModel();
        return result.message;
      }
      if (action === 'clear') {
        await record(role ? await researchApi.clearAgent(role) : await researchApi.clearModel());
        return role ? '已恢复共享默认设置。' : '已清除共享默认设置。';
      }
      const body: ModelConfiguration = {
        provider: status.provider, base_url: form.url.trim(), model: form.model.trim(), api_key: form.key,
        timeout_seconds: Number(form.timeout), temperature: Number(form.temperature), max_output_tokens: Number(form.tokens),
      };
      await record(role ? await researchApi.configureAgent(role, body) : await researchApi.configureModel(body));
      return '连接设置已保存。';
    },
    onSuccess: setMessage,
    onSettled: () => onBusy(false),
  });

  const act = (action: 'save' | 'test' | 'clear') => {
    setMessage('');
    setConfirmClear(false);
    onBusy(true);
    operation.mutate(action);
  };
  const edit = (key: keyof ConnectionDraft, value: string) => {
    const updated = { ...form, [key]: value };
    onDraft(sameDraft(updated, current) ? undefined : updated);
    setConfirmClear(false);
    setMessage('');
    if (operation.isError) operation.reset();
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (dirty && !operation.isPending) act('save');
  };

  return <section className="panel model-editor inspector-enter" aria-labelledby="connection-heading">
    <div className="model-section-heading"><h2 id="connection-heading">{scopeName(scope)}连接配置</h2>
      <span className={'pill ' + (dirty ? 'outline' : 'soft')}>{dirty ? '草稿未保存' : sourceName(status, scope)}</span>
    </div>
    <p className="model-context">{role ? '保存后，此专科将启用独立大模型连接，不再继承默认配置。' : '作为全局基础连接，供所有未单独覆盖的专科自动继承使用。'}配置修改将在下次新建运行时冻结生效。</p>
    <form className="research-form" onSubmit={submit}>
      <fieldset className="editor-fields" disabled={operation.isPending}>
        <legend className="sr-only">模型服务与凭据</legend>
        <label>接口服务地址<input type="url" required autoComplete="off" spellCheck={false} value={form.url}
          onChange={event => edit('url', event.target.value)} placeholder="例如：https://api.deepseek.com/v1" /></label>
        <label>模型名称标识<input required autoComplete="off" spellCheck={false} maxLength={160} value={form.model}
          onChange={event => edit('model', event.target.value)} placeholder="填写服务商提供的模型名称" /></label>
        <label>接口访问密钥<input type="password" autoComplete="new-password" maxLength={1024} required={needKey} value={form.key}
          onChange={event => edit('key', event.target.value)} aria-describedby="api-key-hint"
          placeholder={hasKey && !needKey ? '已加密保存密钥（留空则沿用）' : '输入此连接的访问密钥'} /></label>
        <small id="api-key-hint">{!needKey ? '留空可继续使用已加密保存的密钥。' : hasKey ? '接口服务地址已更改，出于安全策略请重新输入密钥。' : '密钥将在本地使用主密钥加密落库，永不回传前端或写入报告。'}</small>
        <details className="model-parameters">
          <summary>生成控制参数 <span>超时 {form.timeout} 秒 · 温度 {form.temperature} · 上限 {form.tokens} 字词</span></summary>
          <div className="parameter-fields">
            <label>单次请求超时（秒）<input type="number" required min="1" max="60" value={form.timeout} onChange={event => edit('timeout', event.target.value)} /></label>
            <label>采样温度（0–2）<input type="number" required min="0" max="2" step="any" value={form.temperature} onChange={event => edit('temperature', event.target.value)} /></label>
            <label>最大输出字词数<input type="number" required min="128" max="8192" value={form.tokens} onChange={event => edit('tokens', event.target.value)} /></label>
          </div>
        </details>
      </fieldset>
      <InlineError error={operation.error} />
      {message && <p className="model-feedback" role="status"><Icon name="check" size={15} />{message}</p>}
      <div className="model-editor-actions">
        <button type="submit" className="button primary" disabled={!dirty || operation.isPending}>
          {operation.isPending && operation.variables === 'save' ? '正在加密保存…' : '保存连接设置'}</button>
        <button type="button" className="button secondary" disabled={!status.configured || dirty || operation.isPending} onClick={() => act('test')}>
          {operation.isPending && operation.variables === 'test' ? '正在验证连通性…' : '测试已保存连接'}</button>
        {dirty && <button type="button" className="text-link" disabled={operation.isPending} onClick={() => {
          onDraft(); operation.reset(); setMessage('已撤销未保存的草稿修改。');
        }}>撤销修改</button>}
      </div>
      <small className="model-help">请接入支持严格 JSON 结构化输出的兼容 HTTPS 模型服务。点击连接测试将发送一条不含病例数据的握手验证请求。</small>
      {own && !confirmClear && <button type="button" className="text-link model-clear" disabled={operation.isPending}
        onClick={() => { operation.reset(); setMessage(''); setConfirmClear(true); }}>
        {role ? '恢复共享默认设置' : '清除默认连接'}
      </button>}
      {confirmClear && <div className="model-clear-prompt">
        <p>{role ? '恢复后将删除此专科的独立连接和密钥。' : '清除后，继承此连接的专科需要重新配置模型。'}</p>
        <button type="button" className="button secondary" onClick={() => act('clear')}>确认{role ? '恢复' : '清除'}</button>
        <button type="button" className="text-link" onClick={() => setConfirmClear(false)}>取消</button>
      </div>}
    </form>
  </section>;
}
