import { useEffect, useSyncExternalStore } from 'react';
import { checkHostedModel, getHostedModel, subscribeHostedModel } from '../services/browser/hostedModel';

export function useHostedModel() {
  const state = useSyncExternalStore(subscribeHostedModel, getHostedModel, getHostedModel);
  useEffect(() => { void checkHostedModel(); }, []);
  return state;
}
