export interface AppConfig {
  pageTitle: string;
  pageDescription: string;
  companyName: string;

  supportsChatInput: boolean;
  supportsVideoInput: boolean;
  supportsScreenShare: boolean;
  isPreConnectBufferEnabled: boolean;

  logo: string;
  startButtonText: string;
  accent?: string;
  logoDark?: string;
  accentDark?: string;

  audioVisualizerType?: 'bar' | 'wave' | 'grid' | 'radial' | 'aura';
  audioVisualizerColor?: `#${string}`;
  audioVisualizerColorDark?: `#${string}`;
  audioVisualizerColorShift?: number;
  audioVisualizerBarCount?: number;
  audioVisualizerGridRowCount?: number;
  audioVisualizerGridColumnCount?: number;
  audioVisualizerRadialBarCount?: number;
  audioVisualizerRadialRadius?: number;
  audioVisualizerWaveLineWidth?: number;

  // agent dispatch configuration
  agentName?: string;

  // LiveKit Cloud Sandbox configuration
  sandboxId?: string;
}

export const APP_CONFIG_DEFAULTS: AppConfig = {
  companyName: 'Hire Slice',
  pageTitle: 'Hire Slice — order by voice',
  pageDescription: 'Order a pizza by talking to us. Same agent that answers the phone.',

  supportsChatInput: true,
  supportsVideoInput: true,
  supportsScreenShare: true,
  isPreConnectBufferEnabled: true,

  logo: '/hire-slice-lockup.svg',
  // The mark half of the lockup carries its own cream disc, but the wordmark is
  // thin against a dark background — the dark variant lifts those fills only.
  logoDark: '/hire-slice-lockup-dark.svg',
  // getStyles() injects `accent` as --primary, so this one value re-skins every
  // button. It does not set --primary-foreground, whose dark default is near
  // black — hence a light accentDark, so button labels stay legible.
  accent: '#C6362B',
  accentDark: '#F0C9A0',
  startButtonText: 'Start your order',

  // optional: audio visualization configuration
  // audioVisualizerType: 'bar',
  // audioVisualizerColor: '#002cf2',
  // audioVisualizerColorDark: '#1fd5f9',
  // audioVisualizerColorShift: 0.3,
  // audioVisualizerBarCount: 5,
  // audioVisualizerType: 'radial',
  // audioVisualizerRadialBarCount: 24,
  // audioVisualizerRadialRadius: 100,
  // audioVisualizerType: 'grid',
  // audioVisualizerGridRowCount: 25,
  // audioVisualizerGridColumnCount: 25,
  // audioVisualizerType: 'wave',
  // audioVisualizerWaveLineWidth: 3,
  // audioVisualizerType: 'aura',

  // agent dispatch configuration
  agentName: process.env.AGENT_NAME ?? undefined,

  // LiveKit Cloud Sandbox configuration
  sandboxId: undefined,
};
