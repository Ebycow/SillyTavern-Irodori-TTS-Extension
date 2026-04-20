import { registerTtsProvider } from '../tts/index.js';
import { IrodoriTtsProvider } from './irodori.js';

registerTtsProvider('Irodori TTS', IrodoriTtsProvider);
