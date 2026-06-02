import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { App } from '../src/App';

describe('App', () => {
  it('renders the Numerix × Chronos-2 app shell', () => {
    render(<App />);
    // "Numerix"/"Chronos-2" appear in both the Header title and its
    // description, so use getAllByText (getByText throws on >1 match).
    expect(screen.getAllByText(/Numerix/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Chronos-2/).length).toBeGreaterThan(0);
  });

  it('shows a sidebar containing the chat panel and what-if form regions', () => {
    render(<App />);
    expect(screen.getByRole('region', { name: /chat/i })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /what-if/i })).toBeInTheDocument();
  });
});
