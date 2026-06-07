import { useState, FormEvent } from 'react';
import {
  Button,
  ColumnLayout,
  Form,
  FormField,
  Input,
  SpaceBetween,
} from '@cloudscape-design/components';

export interface WhatIfParams {
  as_of_date: string;
  lookback_days: number;
  horizon: number;
  n_paths: number;
  w_stress: number;
  conditioning?: { series_shifts: Record<string, number>; n_anchor_days: number };
}

interface WhatIfFormProps {
  onApply: (p: WhatIfParams) => void;
  disabled: boolean;
}

const DEFAULTS: WhatIfParams = {
  as_of_date: '2020-03-15',
  lookback_days: 1260,
  horizon: 252,
  n_paths: 2000,
  w_stress: 0.5,
};

export function WhatIfForm({ onApply, disabled }: WhatIfFormProps) {
  // Form state is the five scalar fields as strings; `conditioning` is a nested
  // object handled separately via `cond` below, so it is excluded here.
  type FormFields = 'as_of_date' | 'lookback_days' | 'horizon' | 'n_paths' | 'w_stress';
  const [v, setV] = useState<Record<FormFields, string>>({
    as_of_date: DEFAULTS.as_of_date,
    lookback_days: String(DEFAULTS.lookback_days),
    horizon: String(DEFAULTS.horizon),
    n_paths: String(DEFAULTS.n_paths),
    w_stress: String(DEFAULTS.w_stress),
  });
  const [cond, setCond] = useState({ shift_series: '', shift_amount: '0', n_anchor_days: '30' });
  const [err, setErr] = useState<string | null>(null);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const lb = parseInt(v.lookback_days, 10);
    const hz = parseInt(v.horizon, 10);
    const np = parseInt(v.n_paths, 10);
    const w = parseFloat(v.w_stress);
    if (!(w >= 0 && w <= 1)) {
      setErr('w_stress must be between 0 and 1');
      return;
    }
    if (!(lb > 0 && hz > 0 && np > 0)) {
      setErr('lookback_days, horizon, n_paths must be positive');
      return;
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(v.as_of_date)) {
      setErr('as_of_date must be YYYY-MM-DD');
      return;
    }
    setErr(null);
    const base = {
      as_of_date: v.as_of_date,
      lookback_days: lb,
      horizon: hz,
      n_paths: np,
      w_stress: w,
    };
    if (cond.shift_series.trim() !== '') {
      const amt = parseFloat(cond.shift_amount);
      const nad = parseInt(cond.n_anchor_days, 10);
      if (Number.isNaN(amt) || !(nad > 0)) {
        setErr('shift_amount must be numeric and n_anchor_days a positive integer');
        return;
      }
      onApply({
        ...base,
        conditioning: { series_shifts: { [cond.shift_series.trim()]: amt }, n_anchor_days: nad },
      });
      return;
    }
    onApply(base);
  };

  const fld = (key: FormFields, label: string, type = 'text') => (
    <FormField label={label}>
      <Input
        value={v[key]}
        onChange={({ detail }) => setV({ ...v, [key]: detail.value })}
        type={type === 'number' ? 'number' : 'text'}
        ariaLabel={label}
      />
    </FormField>
  );

  return (
    <form onSubmit={submit}>
      <Form
        errorText={err ?? undefined}
        actions={
          // onClick mirrors formAction="submit" so the click path works under
          // happy-dom (which doesn't fire implicit submit for a button nested
          // in Cloudscape's <Form actions> slot); harmless in a real browser.
          <Button
            variant="primary"
            disabled={disabled}
            formAction="submit"
            onClick={() => submit()}
          >
            Apply
          </Button>
        }
      >
        <SpaceBetween size="m">
          <ColumnLayout columns={3}>
            {fld('as_of_date', 'as_of_date')}
            {fld('lookback_days', 'lookback_days', 'number')}
            {fld('horizon', 'horizon', 'number')}
            {fld('n_paths', 'n_paths', 'number')}
            {fld('w_stress', 'w_stress', 'number')}
            <FormField label="shift_series">
              <Input value={cond.shift_series} ariaLabel="shift_series"
                onChange={({ detail }) => setCond({ ...cond, shift_series: detail.value })} />
            </FormField>
            <FormField label="shift_amount">
              <Input value={cond.shift_amount} type="number" ariaLabel="shift_amount"
                onChange={({ detail }) => setCond({ ...cond, shift_amount: detail.value })} />
            </FormField>
            <FormField label="n_anchor_days">
              <Input value={cond.n_anchor_days} type="number" ariaLabel="n_anchor_days"
                onChange={({ detail }) => setCond({ ...cond, n_anchor_days: detail.value })} />
            </FormField>
          </ColumnLayout>
        </SpaceBetween>
      </Form>
    </form>
  );
}
