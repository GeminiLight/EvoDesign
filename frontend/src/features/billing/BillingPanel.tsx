import { useEffect, useState } from 'react';
import type { BackendSubscriptionStatus } from '../../contracts/backendApi.generated';
import { apiV1Url } from '../../services/httpClient';
import { StripeCheckout } from '../stripe/StripeCheckout';
import { useBackendAuth } from '../auth/BackendAuthProvider';

export const BillingPanel = () => {
  const { user, token } = useBackendAuth();
  const [subscription, setSubscription] = useState<BackendSubscriptionStatus | null>(null);

  useEffect(() => {
    if (!user || !token) {
      setSubscription(null);
      return;
    }

    const load = async () => {
      try {
        const res = await fetch(apiV1Url('/users/subscription'), {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) {
          console.error('Failed to load subscription', res.statusText);
          return;
        }
        const data = await res.json() as BackendSubscriptionStatus;
        setSubscription(data);
      } catch (error) {
        console.error('Failed to load subscription', error);
      }
    };

    load();
  }, [user, token]);

  const status = subscription?.subscription?.status ?? 'free';
  const isPro = status === 'active' || status === 'trialing';

  return (
    <div className="rounded-2xl border border-slate-100 bg-white/80 p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Billing</p>
          <h3 className="text-sm font-semibold text-slate-800">Plan: {isPro ? 'Pro' : 'Free'}</h3>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-[10px] font-semibold ${isPro ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-500'}`}>
          {status}
        </span>
      </div>

      <div className="mt-3 space-y-2 text-xs text-slate-600">
        <p>
          {isPro
            ? `You have unlimited access to diagram generation.`
            : `You are on the free plan.`
          }
        </p>
        {!isPro && (
          <p className="text-[11px] text-slate-400">Upgrade to unlock higher generation limits and deeper project history.</p>
        )}
      </div>

      <div className="mt-3">
        {!isPro && (
          <StripeCheckout
            priceId={import.meta.env.VITE_STRIPE_PRICE_ID}
          />
        )}
      </div>
    </div>
  );
};
