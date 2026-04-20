import { saveTtsProviderSettings } from '../tts/index.js';

export { IrodoriTtsProvider };

class IrodoriTtsProvider {
    settings = {};

    constructor() {
        this.settings = {
            provider_endpoint: 'http://127.0.0.1:8799',
            num_steps: 40,
            cfg_scale_text: 3.0,
            cfg_scale_caption: 3.0,
            cfg_scale_speaker: 5.0,
            cfg_guidance_mode: 'independent',
            seconds: 30.0,
            seed: -1,
            trim_tail: true,
            default_caption: '',
            voiceMap: {},
        };
    }

    ready = false;
    voices = [];
    separator = '。';
    modelType = 'base';

    get settingsHtml() {
        const s = this.settings;
        let html = `<div class="irodori-settings-container">
            <div class="irodori-settings-header">
                <h3>Irodori TTS Settings</h3>
                <div class="status-indicator">
                    Status: <span id="irodori-status" class="offline">Offline</span>
                    &nbsp;|&nbsp;
                    Model: <span id="irodori-model-type">—</span>
                </div>
            </div>

            <div class="irodori-setting-row">
                <label for="irodori-endpoint">Server Endpoint:</label>
                <input id="irodori-endpoint" type="text" class="text_pole" value="${s.provider_endpoint}" />
            </div>

            <div class="irodori-params-section">
                <h4>Generation Parameters</h4>

                <div class="irodori-setting-row">
                    <label for="irodori-num-steps">Steps: <span id="irodori-num-steps-value">${s.num_steps}</span></label>
                    <input id="irodori-num-steps" type="range" min="10" max="100" step="1" value="${s.num_steps}" />
                </div>

                <div class="irodori-setting-row">
                    <label for="irodori-cfg-text">CFG Text: <span id="irodori-cfg-text-value">${s.cfg_scale_text}</span></label>
                    <input id="irodori-cfg-text" type="range" min="0" max="10" step="0.5" value="${s.cfg_scale_text}" />
                </div>

                <div class="irodori-setting-row">
                    <label for="irodori-cfg-speaker">CFG Speaker: <span id="irodori-cfg-speaker-value">${s.cfg_scale_speaker}</span></label>
                    <input id="irodori-cfg-speaker" type="range" min="0" max="15" step="0.5" value="${s.cfg_scale_speaker}" />
                </div>

                <div class="irodori-setting-row" id="irodori-cfg-caption-row">
                    <label for="irodori-cfg-caption">CFG Caption: <span id="irodori-cfg-caption-value">${s.cfg_scale_caption}</span></label>
                    <input id="irodori-cfg-caption" type="range" min="0" max="10" step="0.5" value="${s.cfg_scale_caption}" />
                </div>

                <div class="irodori-setting-row">
                    <label for="irodori-guidance-mode">Guidance Mode:</label>
                    <select id="irodori-guidance-mode">
                        <option value="independent" ${s.cfg_guidance_mode === 'independent' ? 'selected' : ''}>Independent</option>
                        <option value="joint" ${s.cfg_guidance_mode === 'joint' ? 'selected' : ''}>Joint</option>
                        <option value="alternating" ${s.cfg_guidance_mode === 'alternating' ? 'selected' : ''}>Alternating</option>
                    </select>
                </div>

                <div class="irodori-setting-row">
                    <label for="irodori-seconds">Output Seconds: <span id="irodori-seconds-value">${s.seconds}</span></label>
                    <input id="irodori-seconds" type="range" min="5" max="60" step="5" value="${s.seconds}" />
                </div>

                <div class="irodori-setting-row">
                    <label for="irodori-seed">Seed (-1 = random):</label>
                    <input id="irodori-seed" class="text_pole" type="number" min="-1" value="${s.seed}" />
                </div>

                <div class="irodori-setting-row">
                    <label class="checkbox_label">
                        <input type="checkbox" id="irodori-trim-tail" ${s.trim_tail ? 'checked' : ''} />
                        Trim trailing silence
                    </label>
                </div>
            </div>

            <div class="irodori-params-section" id="irodori-caption-section">
                <h4>Voice Design Caption (VoiceDesign model only)</h4>
                <div class="irodori-setting-row">
                    <label for="irodori-default-caption">Default Caption:</label>
                    <input id="irodori-default-caption" type="text" class="text_pole"
                        placeholder="e.g. calm female voice, soft, close distance"
                        value="${s.default_caption}" />
                </div>
            </div>

            <div class="irodori-footer">
                <a href="${s.provider_endpoint}/health" target="_blank">Server Health</a>
            </div>
        </div>

        <style>
            .irodori-settings-container { padding: 10px; }
            .irodori-settings-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 15px;
            }
            .irodori-settings-header h3 { margin: 0; }
            #irodori-status.ready { color: #4CAF50; }
            #irodori-status.offline { color: #f44336; }
            #irodori-status.processing { color: #2196F3; }
            .irodori-setting-row {
                margin-bottom: 10px;
                display: flex;
                align-items: center;
                gap: 10px;
            }
            .irodori-setting-row label { flex: 0 0 160px; }
            .irodori-setting-row label.checkbox_label { flex-basis: auto; }
            .irodori-setting-row input[type="text"],
            .irodori-setting-row input[type="number"],
            .irodori-setting-row select { flex: 1; }
            .irodori-setting-row input[type="range"] { flex: 1; }
            .irodori-params-section {
                margin-top: 15px;
                padding-top: 15px;
                border-top: 1px solid #555;
            }
            .irodori-params-section h4 { margin-top: 0; margin-bottom: 10px; }
            .irodori-footer {
                margin-top: 15px;
                padding-top: 15px;
                border-top: 1px solid #555;
                text-align: center;
                font-size: 0.9em;
            }
        </style>`;

        return html;
    }

    async loadSettings(settings) {
        this.updateStatus('Offline');

        if (Object.keys(settings).length > 0) {
            for (const key in settings) {
                if (key in this.settings) {
                    this.settings[key] = settings[key];
                }
            }
        }

        this.updateUIFromSettings();

        try {
            await this.checkReady();
            if (this.ready) {
                await this.fetchTtsVoiceObjects();
                this.updateStatus('Ready');
            } else {
                this.updateStatus('Offline');
            }
            this.setupEventListeners();
        } catch (error) {
            console.error('IrodoriTTS: Error loading settings:', error);
            this.updateStatus('Offline');
        }
    }

    updateUIFromSettings() {
        const s = this.settings;
        $('#irodori-endpoint').val(s.provider_endpoint);
        $('#irodori-num-steps').val(s.num_steps);
        $('#irodori-num-steps-value').text(s.num_steps);
        $('#irodori-cfg-text').val(s.cfg_scale_text);
        $('#irodori-cfg-text-value').text(s.cfg_scale_text);
        $('#irodori-cfg-speaker').val(s.cfg_scale_speaker);
        $('#irodori-cfg-speaker-value').text(s.cfg_scale_speaker);
        $('#irodori-cfg-caption').val(s.cfg_scale_caption);
        $('#irodori-cfg-caption-value').text(s.cfg_scale_caption);
        $('#irodori-guidance-mode').val(s.cfg_guidance_mode);
        $('#irodori-seconds').val(s.seconds);
        $('#irodori-seconds-value').text(s.seconds);
        $('#irodori-seed').val(s.seed);
        $('#irodori-trim-tail').prop('checked', s.trim_tail);
        $('#irodori-default-caption').val(s.default_caption);
        this.updateModelTypeUI();
    }

    updateModelTypeUI() {
        const isVoiceDesign = this.modelType === 'voicedesign';
        $('#irodori-model-type').text(isVoiceDesign ? 'VoiceDesign' : 'Base');
        if (isVoiceDesign) {
            $('#irodori-caption-section').show();
            $('#irodori-cfg-caption-row').show();
        } else {
            $('#irodori-caption-section').hide();
            $('#irodori-cfg-caption-row').hide();
        }
    }

    async checkReady() {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 5000);
        try {
            const response = await fetch(`${this.settings.provider_endpoint}/health`, { signal: controller.signal });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            this.ready = true;
            this.modelType = data.model_type || 'base';
            this.updateModelTypeUI();
        } catch (error) {
            console.error('IrodoriTTS: Server not available:', error);
            this.ready = false;
        } finally {
            clearTimeout(timeout);
        }
    }

    async fetchTtsVoiceObjects() {
        try {
            const response = await fetch(`${this.settings.provider_endpoint}/voices`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            this.voices = data.map(v => ({
                name: v.name,
                voice_id: v.voice_id,
                preview_url: v.preview_url || null,
                lang: v.lang || 'ja',
            }));
            return this.voices;
        } catch (error) {
            console.error('IrodoriTTS: Failed to fetch voices:', error);
            this.voices = [{ name: '[No Reference]', voice_id: 'no_ref', preview_url: null, lang: 'ja' }];
            return this.voices;
        }
    }

    setupEventListeners() {
        $('#irodori-endpoint').on('input', () => {
            this.settings.provider_endpoint = $('#irodori-endpoint').val();
            saveTtsProviderSettings();
        });

        const sliders = [
            ['#irodori-num-steps', '#irodori-num-steps-value', 'num_steps', parseInt],
            ['#irodori-cfg-text', '#irodori-cfg-text-value', 'cfg_scale_text', parseFloat],
            ['#irodori-cfg-speaker', '#irodori-cfg-speaker-value', 'cfg_scale_speaker', parseFloat],
            ['#irodori-cfg-caption', '#irodori-cfg-caption-value', 'cfg_scale_caption', parseFloat],
            ['#irodori-seconds', '#irodori-seconds-value', 'seconds', parseFloat],
        ];
        for (const [inputId, labelId, key, parse] of sliders) {
            $(inputId).on('input', (e) => {
                this.settings[key] = parse(e.target.value);
                $(labelId).text(this.settings[key]);
                saveTtsProviderSettings();
            });
        }

        $('#irodori-guidance-mode').on('change', (e) => {
            this.settings.cfg_guidance_mode = e.target.value;
            saveTtsProviderSettings();
        });

        $('#irodori-seed').on('change', (e) => {
            this.settings.seed = parseInt(e.target.value);
            saveTtsProviderSettings();
        });

        $('#irodori-trim-tail').on('change', (e) => {
            this.settings.trim_tail = e.target.checked;
            saveTtsProviderSettings();
        });

        $('#irodori-default-caption').on('input', () => {
            this.settings.default_caption = $('#irodori-default-caption').val();
            saveTtsProviderSettings();
        });
    }

    async onRefreshClick() {
        this.updateStatus('Processing');
        await this.checkReady();
        if (this.ready) {
            await this.fetchTtsVoiceObjects();
            this.updateStatus('Ready');
        } else {
            this.updateStatus('Offline');
        }
    }

    async getVoice(voiceName) {
        if (this.voices.length === 0) await this.fetchTtsVoiceObjects();

        const match = this.voices.find(v => v.name === voiceName || v.voice_id === voiceName);
        if (match) return match;

        if (voiceName && voiceName.startsWith('ref_')) {
            const filename = voiceName.slice(4);
            return { name: `[Ref] ${filename}`, voice_id: voiceName, preview_url: null, lang: 'ja' };
        }

        return { name: voiceName || '[No Reference]', voice_id: voiceName || 'no_ref', preview_url: null, lang: 'ja' };
    }

    async generateTts(text, voiceId) {
        this.updateStatus('Processing');
        try {
            const seed = this.settings.seed >= 0 ? this.settings.seed : null;
            const caption = this.modelType === 'voicedesign' && this.settings.default_caption
                ? this.settings.default_caption
                : null;

            const body = {
                text,
                voice_id: voiceId || 'no_ref',
                caption,
                num_steps: this.settings.num_steps,
                cfg_scale_text: this.settings.cfg_scale_text,
                cfg_scale_caption: this.settings.cfg_scale_caption,
                cfg_scale_speaker: this.settings.cfg_scale_speaker,
                cfg_guidance_mode: this.settings.cfg_guidance_mode,
                seconds: this.settings.seconds,
                seed,
                trim_tail: this.settings.trim_tail,
            };

            const response = await fetch(`${this.settings.provider_endpoint}/tts`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(`HTTP ${response.status}: ${errorText}`);
            }

            this.updateStatus('Ready');
            return response;
        } catch (error) {
            this.updateStatus('Ready');
            throw error;
        }
    }

    async previewTtsVoice(voiceId) {
        const previewText = 'こんにちは。これは音声のプレビューです。';
        const response = await this.generateTts(previewText, voiceId);
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audio.addEventListener('ended', () => URL.revokeObjectURL(url));
        await audio.play();
    }

    updateStatus(status) {
        const el = document.getElementById('irodori-status');
        if (el) {
            el.textContent = status;
            el.className = status.toLowerCase();
        }
    }
}
