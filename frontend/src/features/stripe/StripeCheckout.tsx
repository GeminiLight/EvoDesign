/**
 * Simplified Stripe Checkout (without Edge Functions)
 * 直接使用 Stripe SDK，无需后端
 */

import { useEffect, useState } from 'react';
import { loadStripe } from '@stripe/stripe-js';

const stripePromise = loadStripe(import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY || '');

type RedirectCheckoutClient = {
  redirectToCheckout: (options: {
    lineItems: Array<{ price: string; quantity: number }>;
    mode: 'subscription';
    successUrl: string;
    cancelUrl: string;
  }) => Promise<{ error?: { message?: string } }>;
};

interface StripeCheckoutProps {
  priceId?: string;
  onSuccess?: () => void;
  onCancel?: () => void;
}

export const StripeCheckout = ({ priceId, onSuccess, onCancel }: StripeCheckoutProps) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const checkoutStatus = new URLSearchParams(window.location.search).get('checkout');
    if (checkoutStatus === 'cancel') {
      onCancel?.();
    }
  }, [onCancel]);

  const handleCheckout = async () => {
    if (!priceId) {
      setError('Price ID not configured');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const stripe = await stripePromise;
      if (!stripe) {
        throw new Error('Stripe failed to load');
      }

      const checkoutClient = stripe as unknown as RedirectCheckoutClient;
      const { error } = await checkoutClient.redirectToCheckout({
        lineItems: [{ price: priceId, quantity: 1 }],
        mode: 'subscription',
        successUrl: `${window.location.origin}?checkout=success`,
        cancelUrl: `${window.location.origin}?checkout=cancel`,
      });

      if (error) {
        setError(error.message || 'Checkout failed');
      } else if (onSuccess) {
        onSuccess();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Checkout failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-2">
      <button
        onClick={handleCheckout}
        disabled={loading || !priceId}
        className="w-full rounded-xl bg-brand-600 px-3 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-brand-700 disabled:opacity-60"
      >
        {loading ? 'Processing...' : 'Upgrade to Pro'}
      </button>
      {error && (
        <p className="text-xs font-medium text-red-600 dark:text-red-300" role="alert">
          {error}
        </p>
      )}
    </div>
  );
};

export default StripeCheckout;
