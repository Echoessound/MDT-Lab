import { useId } from 'react';
import type { ModelConfiguration } from './api';
import type { ModelStatus } from './schemas';

export type ConnectionDraft = { url: string; model: string; key: string; timeout: string; temperature: string; tokens: string };

export function draftFrom(status?: ModelStatus): ConnectionDraft {
  return {
    url: status?.base_url ?? '', model: status?.model ?? '', key: '',
    timeout: String(status?.timeout_seconds ?? 20), temperature: String(status?.temperature ?? 0),
    tokens: String(status?.max_output_tokens ?? 1200),
  };
}

export function sameDraft(a: ConnectionDraft, b: ConnectionDraft) {
  return (Object.keys(a) as (keyof ConnectionDraft)[]).every(key => a[key] === b[key]);
}

export function configurationFrom(form: ConnectionDraft, provider = 'openai-compatible'): ModelConfiguration {
  return {
    provider, base_url: form.url.trim(), model: form.model.trim(), api_key: form.key,
    timeout_seconds: Number(form.timeout), temperature: Number(form.temperature), max_output_tokens: Number(form.tokens),
  };
}

const normalizedUrl = (url: string) => url.trim().replace(/\/+$/, '');

export function ConnectionFields({ form, savedKeyUrl, disabled, onChange }: {
  form: ConnectionDraft; savedKeyUrl?: string; disabled: boolean;
  onChange: (key: keyof ConnectionDraft, value: string) => void;
}) {
  const keyHint = useId();
  const canReuseKey = savedKeyUrl !== undefined && normalizedUrl(form.url) === normalizedUrl(savedKeyUrl);
  return <fieldset className="editor-fields" disabled={disabled}>
    <legend className="sr-only">模型服务与凭据</legend>
    <label>接口服务地址<input type="url" required autoComplete="off" spellCheck={false} value={form.url}
      onChange={event => onChange('url', event.target.value)} placeholder="https://服务地址/v1" /></label>
    <label>模型名称标识<input required autoComplete="off" spellCheck={false} maxLength={160} value={form.model}
      onChange={event => onChange('model', event.target.value)} placeholder="填写服务商提供的模型名称" /></label>
    <label>接口访问密钥<input type="password" autoComplete="new-password" maxLength={1024} required={!canReuseKey} value={form.key}
      onChange={event => onChange('key', event.target.value)} aria-describedby={keyHint}
      placeholder={canReuseKey ? '留空沿用已保存的密钥' : '输入此连接的访问密钥'} /></label>
    <small id={keyHint}>{canReuseKey ? '密钥已加密保存。' : savedKeyUrl ? '更换接口地址后，请重新输入密钥。' : '密钥在本地加密保存。'}</small>
    <details className="model-parameters">
      <summary>生成控制参数 <span>超时 {form.timeout} 秒 · 温度 {form.temperature} · 上限 {form.tokens} tokens</span></summary>
      <div className="parameter-fields">
        <label>单次请求超时（秒）<input type="number" required min="1" max="60" value={form.timeout}
          onChange={event => onChange('timeout', event.target.value)} /></label>
        <label>采样温度（0–2）<input type="number" required min="0" max="2" step="any" value={form.temperature}
          onChange={event => onChange('temperature', event.target.value)} /></label>
        <label>最大输出 Token 数<input type="number" required min="128" max="8192" value={form.tokens}
          onChange={event => onChange('tokens', event.target.value)} /></label>
      </div>
    </details>
  </fieldset>;
}
