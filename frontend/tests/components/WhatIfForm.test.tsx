import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WhatIfForm } from '../../src/components/WhatIfForm';

describe('WhatIfForm', () => {
  it('renders default values', () => {
    render(<WhatIfForm onApply={vi.fn()} disabled={false} />);
    expect((screen.getByLabelText(/w_stress/i) as HTMLInputElement).value).toBe('0.5');
    expect((screen.getByLabelText(/horizon/i) as HTMLInputElement).value).toBe('252');
  });

  it('calls onApply with parsed numeric values', async () => {
    const onApply = vi.fn();
    render(<WhatIfForm onApply={onApply} disabled={false} />);
    await userEvent.clear(screen.getByLabelText(/w_stress/i));
    await userEvent.type(screen.getByLabelText(/w_stress/i), '0.8');
    await userEvent.click(screen.getByRole('button', { name: /apply/i }));
    expect(onApply).toHaveBeenCalledWith(
      expect.objectContaining({ w_stress: 0.8, horizon: 252, n_paths: 2000 }),
    );
  });

  it('rejects w_stress outside [0,1]', async () => {
    const onApply = vi.fn();
    render(<WhatIfForm onApply={onApply} disabled={false} />);
    await userEvent.clear(screen.getByLabelText(/w_stress/i));
    await userEvent.type(screen.getByLabelText(/w_stress/i), '1.5');
    await userEvent.click(screen.getByRole('button', { name: /apply/i }));
    expect(onApply).not.toHaveBeenCalled();
    // Cloudscape <Form errorText> renders the message twice (visible node +
    // hidden ARIA live-region), so getByText throws on >1 match.
    expect(screen.getAllByText(/between 0 and 1/i).length).toBeGreaterThan(0);
  });

  it('disables apply when disabled prop is true', () => {
    render(<WhatIfForm onApply={vi.fn()} disabled={true} />);
    expect(screen.getByRole('button', { name: /apply/i })).toBeDisabled();
  });
});
