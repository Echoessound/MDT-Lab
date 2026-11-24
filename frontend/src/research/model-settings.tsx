import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { ErrorState, Icon, Loading } from '../ui';
import { researchApi } from './api';
import { configurationFrom, ConnectionFields, draftFrom, sameDraft, type ConnectionDraft } from './model-connection-fields';
import { ModelProfiles, scopeName, type ModelScope } from './model-profiles';
import { InlineError } from './components';
import { roleSchema, type AgentModelStatus, type ModelStatus, type Role } from './schemas';
import { StorageStatus } from './storage-status';
import './agent-console.css';

export function selectedModelsReady(selected: Role[] | undefined, models: AgentModelStatus[] | undefined) {
  return !!selected?.length && selected.every(role => models?.some(item => item.agent_id === role && item.configured));
}

function sourceName(status: ModelStatus, scope: ModelScope) {
  if (!status.configured) return '未配置';
  if (scope === 'default') return '已配置';
  return 'overridden' in status && status.overridden ? '独立配置' : '继承默认';
}

export function ModelSettingsPage() {
  const shared = useQuery({ queryKey: ['research-model'], queryFn: researchApi.modelStatus });
  const agents = useQuery({ queryKey: ['research-agent-models'], queryFn: researchApi.agentModels });
  const [params, setParams] = useSearchParams();
  const requested = roleSchema.safeParse(params.get('agent'));
  const scope: ModelScope = requested.success ? requested.data : 'default';
  // Drafts stay in component memory so switching specialists does not discard edits.
  const [drafts, setDrafts] = useState<Partial<Record<ModelScope, ConnectionDraft>>>({});
  const [busy, setBusy] = useState(false);
  const status = scope === 'default' ? shared.data : agents.data?.find(item => item.agent_id === scope);

  const selectScope = (value: ModelScope) => setParams(next => {
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
        <p>管理可复用的连接方案，为共享默认或指定专科选择模型。</p>
      </div>
      <Link className="button secondary" to="/research/agents"><Icon name="network" size={15} />多智能体协同</Link>
    </header>
    {shared.isPending || agents.isPending ? <Loading /> : shared.isError || agents.isError ?
      <ErrorState error={shared.error ?? agents.error} retry={() => { void shared.refetch(); void agents.refetch(); }} /> :
      <div className="model-workspace">
        <section className="panel model-roster" aria-label="模型连接列表">
          <div className="model-section-heading"><h2>连接列表</h2></div>
          {[{ scope: 'default' as ModelScope, status: shared.data }, ...agents.data.map(agent => ({ scope: agent.agent_id, status: agent }))].map(item => (
            <button key={item.scope} type="button" aria-pressed={item.scope === scope} disabled={busy && item.scope !== scope}
              onClick={() => selectScope(item.scope)} className="model-connection">
              <span className="model-connection-name"><strong>{scopeName(item.scope)}</strong>
                {drafts[item.scope] && <small className="draft-marker">未保存</small>}
              </span>
              <span className="model-summary">{item.status.profile_name || item.status.model || '—'}<span>{sourceName(item.status, item.scope)}</span></span>
            </button>
          ))}
        </section>
        {status && <div className="model-settings-panels">
          <ModelProfiles scope={scope} status={status} shared={shared.data} agents={agents.data} dirtyConnection={!!drafts[scope]}
            busy={busy} onBusy={setBusy} />
          <ConnectionEditor key={scope} scope={scope} status={status} draft={drafts[scope]}
            onDraft={updateDraft} onBusy={setBusy} busy={busy} />
        </div>}
      </div>}
    <StorageStatus />
  </div>;
}

type EditorProps = {
  scope: ModelScope; status: ModelStatus; draft?: ConnectionDraft;
  onDraft: (draft?: ConnectionDraft) => void; onBusy: (value: boolean) => void; busy: boolean;
};

function ConnectionEditor({ scope, status, draft, onDraft, onBusy, busy }: EditorProps) {
  const client = useQueryClient();
  const [message, setMessage] = useState('');
  const [confirmClear, setConfirmClear] = useState(false);
  const current = draftFrom(status);
  const form = draft ?? current;
  const dirty = draft !== undefined;
  const role = scope === 'default' ? undefined : scope;
  const own = role ? 'overridden' in status && !!status.overridden : status.has_api_key;
  const hasKey = own && status.has_api_key && !status.profile_id;
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
      const body = configurationFrom(form, status.provider);
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
    if (dirty && !busy) act('save');
  };

  return <section className="panel model-editor inspector-enter" aria-labelledby="connection-heading">
    <div className="model-section-heading"><h2 id="connection-heading">{scopeName(scope)}直接配置</h2>
      <span className={'pill ' + (dirty ? 'outline' : 'soft')}>{dirty ? '草稿未保存' : sourceName(status, scope)}</span>
    </div>
    <p className="model-context">{status.profile_id
      ? '当前使用「' + status.profile_name + '」。保存直接配置将为' + scopeName(scope) + '建立独立连接，请填写其密钥。'
      : role ? '保存后，此专科使用独立连接。' : '未单独配置的专科会继承此连接。'}</p>
    <form className="research-form" onSubmit={submit}>
      <ConnectionFields form={form} savedKeyUrl={hasKey ? status.base_url : undefined} onChange={edit} disabled={busy} />
      <InlineError error={operation.error} />
      {message && <p className="model-feedback" role="status"><Icon name="check" size={15} />{message}</p>}
      <div className="model-editor-actions">
        <button type="submit" className="button primary" disabled={!dirty || busy}>
          {operation.isPending && operation.variables === 'save' ? '正在加密保存…' : '保存连接设置'}</button>
        <button type="button" className="button secondary" disabled={!status.configured || dirty || busy} onClick={() => act('test')}>
          {operation.isPending && operation.variables === 'test' ? '正在验证连通性…' : '测试已保存连接'}</button>
        {dirty && <button type="button" className="text-link" disabled={busy} onClick={() => {
          onDraft(); operation.reset(); setMessage('已撤销未保存的草稿修改。');
        }}>撤销修改</button>}
      </div>
      <small className="model-help">请接入支持严格 JSON 结构化输出的兼容 HTTPS 模型服务。点击连接测试将发送一条不含病例数据的握手验证请求。</small>
      {own && !confirmClear && <button type="button" className="text-link model-clear" disabled={busy}
        onClick={() => { operation.reset(); setMessage(''); setConfirmClear(true); }}>
        {role ? '恢复共享默认设置' : '清除默认连接'}
      </button>}
      {confirmClear && <div className="model-clear-prompt">
        <p>{status.profile_id ? '解除当前方案绑定后，' + (role ? '此专科将继承共享默认。' : '继承共享默认的专科需重新配置连接。')
          : role ? '恢复后将删除此专科的独立连接和密钥。' : '清除后，继承此连接的专科需要重新配置模型。'}
          {dirty && '此范围内尚未保存的直接配置草稿也将清除。'}</p>
        <button type="button" className="button secondary" disabled={busy} onClick={() => act('clear')}>确认{role ? '恢复' : '清除'}</button>
        <button type="button" className="text-link" disabled={busy} onClick={() => setConfirmClear(false)}>取消</button>
      </div>}
    </form>
  </section>;
}
