import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useBackendAuth } from '../features/auth/BackendAuthProvider';
import { consumeAuthReturnTo } from '../features/auth/authRedirect';
import { AppLoadingScreen } from '../components/AppLoadingScreen';
import { LandingPage } from './LandingPage';
import { defaultConfigs } from '../constants/app';
import type { DiagramType } from '../types/api';

export const IndexPage = () => {
  const { loading, user } = useBackendAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!loading && user) {
      navigate(consumeAuthReturnTo(), { replace: true });
    }
  }, [loading, user, navigate]);

  if (loading) {
    return <AppLoadingScreen />;
  }

  const handleGeneratePrompt = (prompt: string, diagramType: DiagramType) => {
    const llmConfigId = defaultConfigs[0]?.id ?? 'default';
    navigate('/workspace', {
      state: {
        initialPrompt: prompt,
        initialDiagramType: diagramType,
        initialLlmConfigId: llmConfigId,
        initialCanvasMode: 'excalidraw',
        initialSource: 'landing',
        preflightGeneration: true,
        preflightKind: 'startup',
      },
    });
  };

  return (
    <LandingPage
      onEnterGuest={() => navigate('/home')}
      onGeneratePrompt={handleGeneratePrompt}
      onEnterEmailAuth={() => navigate('/auth/email')}
    />
  );
};
