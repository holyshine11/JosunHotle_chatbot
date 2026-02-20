/**
 * TTS 엔진 모듈 — 이중 모드 (Edge TTS + Web Speech API)
 *
 * Edge 모드: 서버 /tts 엔드포인트 → audio/mpeg 문장 단위 재생 + 프리페칭
 * Browser 모드: Web Speech API (폴백)
 *
 * 핵심 흐름:
 *   play() → edge 모드면 _playEdge() / browser 모드면 _playBrowser()
 *   _playEdge(): 문장 분할 → 문장[0] fetch → 재생 + 다음 2문장 프리페치
 *             → 첫 문장 실패 시 browser 폴백
 *             → 중간 문장 실패 시 남은 문장만 browser 폴백
 */
const TTSEngine = {
  _synth: window.speechSynthesis || null,
  _utterances: [],       // browser 모드: 분할된 발화 큐
  _currentIdx: 0,        // 현재 재생 인덱스
  _currentMsgId: null,   // 현재 재생 메시지 ID
  _state: 'idle',        // idle | loading | playing | paused
  _voice: null,          // browser 모드: 선택된 음성
  _voiceLoaded: false,   // browser 음성 로드 완료
  _availableVoices: [],  // browser 한국어 음성 목록
  _pauseTimer: null,     // 문장 간 쉼 타이머

  // Edge TTS 프로퍼티
  _mode: 'edge',                // 'edge' | 'browser'
  _edgeAvailable: true,         // edge 서버 사용 가능 여부
  _edgeCurrentAudio: null,      // 현재 재생 중인 Audio 객체
  _prefetchPool: new Map(),     // key: 문장 텍스트, value: Promise<Blob>
  _sentences: [],               // edge 모드 문장 목록
  _edgeSentenceIdx: 0,          // edge 모드 현재 문장 인덱스

  // Edge 음성 목록 (하드코딩 — Microsoft Azure Neural TTS)
  _edgeVoices: [
    { name: 'ko-KR-SunHiNeural', label: 'SunHi (여성)', gender: 'F' },
    { name: 'ko-KR-InJoonNeural', label: 'InJoon (남성)', gender: 'M' },
    { name: 'ko-KR-BongJinNeural', label: 'BongJin (남성)', gender: 'M' },
    { name: 'ko-KR-GookMinNeural', label: 'GookMin (남성)', gender: 'M' },
    { name: 'ko-KR-JiMinNeural', label: 'JiMin (여성)', gender: 'F' },
    { name: 'ko-KR-SeoHyeonNeural', label: 'SeoHyeon (여성)', gender: 'F' },
    { name: 'ko-KR-SoonBokNeural', label: 'SoonBok (여성)', gender: 'F' },
    { name: 'ko-KR-YuJinNeural', label: 'YuJin (여성)', gender: 'F' },
  ],
  _edgeVoiceName: 'ko-KR-SunHiNeural',  // edge 기본 음성

  // 기본 설정값
  _defaults: {
    rate: 1.0,
    pitch: 1.0,
    volume: 1.0,
    pauseBetween: 200
  },

  // 현재 설정 (init 시 localStorage 복원)
  _settings: null,

  // 콜백
  onStateChange: null,  // (msgId, state) => void

  /**
   * TTS 사용 가능 여부
   */
  isAvailable() {
    return this._mode === 'edge' || !!this._synth;
  },

  /**
   * 현재 모드 반환
   */
  getMode() {
    return this._mode;
  },

  /**
   * 모드 변경
   */
  setMode(mode) {
    if (mode !== 'edge' && mode !== 'browser') return;
    this.stop();
    this._mode = mode;
    localStorage.setItem('tts_mode', mode);
  },

  /**
   * 초기화: 설정 복원 + 음성 선택
   */
  init() {
    // localStorage에서 설정 복원
    this._loadSettings();

    // 모드 복원
    const savedMode = localStorage.getItem('tts_mode');
    if (savedMode === 'edge' || savedMode === 'browser') {
      this._mode = savedMode;
    }

    // Edge 음성 복원
    const savedEdgeVoice = localStorage.getItem('tts_edgeVoiceName');
    if (savedEdgeVoice && this._edgeVoices.some(v => v.name === savedEdgeVoice)) {
      this._edgeVoiceName = savedEdgeVoice;
    }

    // Browser 음성 초기화 (Web Speech API)
    if (this._synth) {
      const selectVoice = () => {
        const voices = this._synth.getVoices();
        if (!voices.length) return;

        const koVoices = voices.filter(v => v.lang && v.lang.startsWith('ko'));
        this._availableVoices = koVoices
          .map(v => ({ voice: v, score: this._scoreVoice(v) }))
          .sort((a, b) => b.score - a.score)
          .map(item => item.voice);

        if (this._availableVoices.length > 0) {
          const savedName = localStorage.getItem('tts_voiceName');
          if (savedName) {
            const saved = this._availableVoices.find(v => v.name === savedName);
            this._voice = saved || this._availableVoices[0];
          } else {
            this._voice = this._availableVoices[0];
          }
        }
        this._voiceLoaded = true;
      };

      if (this._synth.getVoices().length > 0) {
        selectVoice();
      }
      this._synth.onvoiceschanged = selectVoice;
    }
  },

  /**
   * 음성 품질 점수 (browser 모드)
   */
  _scoreVoice(voice) {
    let score = 0;
    const name = voice.name.toLowerCase();
    if (/enhanced/i.test(name))  score += 40;
    if (/neural/i.test(name))    score += 35;
    if (/premium/i.test(name))   score += 30;
    if (/yuna/i.test(name))      score += 20;
    if (/sora/i.test(name))      score += 10;
    if (voice.localService)      score += 5;
    if (voice.lang === 'ko-KR')  score += 3;
    return score;
  },

  // ========== 설정 관리 ==========

  _loadSettings() {
    this._settings = { ...this._defaults };
    try {
      const saved = localStorage.getItem('tts_settings');
      if (saved) {
        const parsed = JSON.parse(saved);
        for (const key of Object.keys(this._defaults)) {
          if (typeof parsed[key] === 'number') {
            this._settings[key] = parsed[key];
          }
        }
      }
    } catch (e) { /* 기본값 사용 */ }
  },

  _saveSettings() {
    try {
      localStorage.setItem('tts_settings', JSON.stringify(this._settings));
    } catch (e) { /* 무시 */ }
  },

  updateSettings(newSettings) {
    for (const key of Object.keys(this._defaults)) {
      if (typeof newSettings[key] === 'number') {
        this._settings[key] = newSettings[key];
      }
    }
    this._saveSettings();
  },

  getSettings() {
    return { ...this._settings };
  },

  // ========== 음성 관리 ==========

  /**
   * 음성 변경 (모드에 따라 분기)
   */
  setVoice(voiceName) {
    if (this._mode === 'edge') {
      if (this._edgeVoices.some(v => v.name === voiceName)) {
        this._edgeVoiceName = voiceName;
        localStorage.setItem('tts_edgeVoiceName', voiceName);
      }
    } else {
      const found = this._availableVoices.find(v => v.name === voiceName);
      if (found) {
        this._voice = found;
        localStorage.setItem('tts_voiceName', voiceName);
      }
    }
  },

  /**
   * 현재 음성 이름 반환
   */
  getCurrentVoiceName() {
    if (this._mode === 'edge') return this._edgeVoiceName;
    return this._voice ? this._voice.name : null;
  },

  /**
   * 사용 가능 음성 목록 (모드별)
   */
  getAvailableVoices() {
    if (this._mode === 'edge') {
      return this._edgeVoices.map(v => ({
        name: v.name,
        lang: 'ko-KR',
        label: v.label,
        score: v.name === 'ko-KR-SunHiNeural' ? 50 : v.name === 'ko-KR-InJoonNeural' ? 45 : 30
      }));
    }
    return this._availableVoices.map(v => ({
      name: v.name,
      lang: v.lang,
      score: this._scoreVoice(v)
    }));
  },

  // ========== 재생 제어 ==========

  /**
   * 텍스트 재생 (모드에 따라 분기)
   */
  async play(text, msgId) {
    if (!text) return;
    if (this._state !== 'idle') {
      this.stop();
    }

    // 전처리
    const processed = TTSPreprocessor.process(text);
    if (!processed) return;

    this._currentMsgId = msgId;
    this._setState('loading');

    if (this._mode === 'edge' && this._edgeAvailable) {
      await this._playEdge(processed);
    } else {
      await this._playBrowser(processed);
    }
  },

  /**
   * 일시정지
   */
  pause() {
    if (this._state !== 'playing') return;

    if (this._pauseTimer) {
      clearTimeout(this._pauseTimer);
      this._pauseTimer = null;
    }

    if (this._mode === 'edge' && this._edgeCurrentAudio) {
      this._edgeCurrentAudio.pause();
      this._setState('paused');
    } else if (this._synth) {
      this._synth.pause();
      this._setState('paused');
    }
  },

  /**
   * 재개
   */
  resume() {
    if (this._state !== 'paused') return;

    if (this._mode === 'edge' && this._edgeCurrentAudio) {
      this._edgeCurrentAudio.play();
      this._setState('playing');
    } else if (this._synth) {
      this._synth.resume();
      this._setState('playing');
    }
  },

  /**
   * 정지
   */
  stop() {
    if (this._pauseTimer) {
      clearTimeout(this._pauseTimer);
      this._pauseTimer = null;
    }

    // Edge 오디오 정지
    if (this._edgeCurrentAudio) {
      this._edgeCurrentAudio.pause();
      this._edgeCurrentAudio.removeAttribute('src');
      this._edgeCurrentAudio = null;
    }

    // 프리페치 풀 정리
    this._prefetchPool.clear();
    this._sentences = [];
    this._edgeSentenceIdx = 0;

    // Browser 정지
    if (this._synth) {
      this._synth.cancel();
    }
    this._utterances = [];
    this._currentIdx = 0;

    this._setState('idle');
  },

  /**
   * 재생/일시정지 토글
   */
  toggle(text, msgId) {
    if (this._state === 'idle' || this._currentMsgId !== msgId) {
      this.play(text, msgId);
    } else if (this._state === 'playing') {
      this.pause();
    } else if (this._state === 'paused') {
      this.resume();
    }
  },

  // ========== Edge TTS ==========

  /**
   * Edge 모드 재생
   */
  async _playEdge(processed) {
    const sentences = this._splitSentences(processed);
    if (sentences.length === 0) {
      this._setState('idle');
      return;
    }

    this._sentences = sentences;
    this._edgeSentenceIdx = 0;

    // 첫 문장 fetch
    try {
      const blob = await this._fetchEdgeAudio(sentences[0]);
      // 첫 문장 성공 → 재생 시작
      this._prefetchNext(1);  // 다음 2문장 프리페치
      await this._playEdgeBlob(blob);
      // 첫 문장 재생 완료 → 다음 문장 진행
      this._edgeSentenceIdx = 1;
      this._playNextEdgeSentence();
    } catch (e) {
      console.warn('[TTS] Edge 첫 문장 실패, browser 폴백:', e.message);
      this._edgeAvailable = false;
      this._mode = 'browser';
      localStorage.setItem('tts_mode', 'browser');
      await this._playBrowser(processed);
    }
  },

  /**
   * Edge 다음 문장 재생 (재귀)
   */
  async _playNextEdgeSentence() {
    if (this._edgeSentenceIdx >= this._sentences.length) {
      // 모든 문장 완료
      this._prefetchPool.clear();
      this._sentences = [];
      this._setState('idle');
      return;
    }

    // 현재 재생이 중단되었으면 종료
    if (this._state === 'idle') return;

    const sentence = this._sentences[this._edgeSentenceIdx];

    // 문장 간 쉼
    const pause = this._settings.pauseBetween || 0;
    if (pause > 0) {
      await new Promise(resolve => {
        this._pauseTimer = setTimeout(() => {
          this._pauseTimer = null;
          resolve();
        }, pause);
      });
    }

    // 정지 확인
    if (this._state === 'idle') return;

    try {
      // 프리페치 풀에서 가져오거나 새로 fetch
      let blob;
      if (this._prefetchPool.has(sentence)) {
        blob = await this._prefetchPool.get(sentence);
      } else {
        blob = await this._fetchEdgeAudio(sentence);
      }

      // 다음 문장 프리페치
      this._prefetchNext(this._edgeSentenceIdx + 1);

      await this._playEdgeBlob(blob);

      this._edgeSentenceIdx++;
      this._playNextEdgeSentence();
    } catch (e) {
      console.warn(`[TTS] Edge 문장 #${this._edgeSentenceIdx} 실패, 남은 문장 browser 폴백`);
      this._fallbackRemainingToBrowser();
    }
  },

  /**
   * 서버 /tts 엔드포인트에서 오디오 fetch
   */
  async _fetchEdgeAudio(text) {
    const params = new URLSearchParams({
      text: text,
      voice: this._edgeVoiceName,
      rate: this._toEdgeRate(this._settings.rate),
      pitch: this._toEdgePitch(this._settings.pitch),
    });

    const baseUrl = (window.location.port !== '8000')
      ? 'http://localhost:8000'
      : '';

    const resp = await fetch(`${baseUrl}/tts?${params}`);
    if (!resp.ok) throw new Error(`TTS HTTP ${resp.status}`);
    return await resp.blob();
  },

  /**
   * Audio 객체로 Blob 재생 (Promise 반환)
   */
  _playEdgeBlob(blob) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.volume = this._settings.volume;
      this._edgeCurrentAudio = audio;

      audio.onplay = () => {
        if (this._state === 'loading') {
          this._setState('playing');
        }
      };

      audio.onended = () => {
        URL.revokeObjectURL(url);
        this._edgeCurrentAudio = null;
        resolve();
      };

      audio.onerror = (e) => {
        URL.revokeObjectURL(url);
        this._edgeCurrentAudio = null;
        reject(new Error('Audio 재생 오류'));
      };

      audio.play().catch(reject);
    });
  },

  /**
   * 다음 N문장 프리페치 (최대 2문장)
   */
  _prefetchNext(fromIdx) {
    for (let i = fromIdx; i < Math.min(fromIdx + 2, this._sentences.length); i++) {
      const s = this._sentences[i];
      if (!this._prefetchPool.has(s)) {
        this._prefetchPool.set(s, this._fetchEdgeAudio(s).catch(() => null));
      }
    }
  },

  /**
   * 남은 문장 Web Speech API 폴백
   */
  _fallbackRemainingToBrowser() {
    if (this._edgeCurrentAudio) {
      this._edgeCurrentAudio.pause();
      this._edgeCurrentAudio = null;
    }
    this._prefetchPool.clear();

    const remaining = this._sentences.slice(this._edgeSentenceIdx).join('. ');
    this._sentences = [];

    if (remaining && this._synth) {
      this._playBrowserDirect(remaining);
    } else {
      this._setState('idle');
    }
  },

  /**
   * 슬라이더 0.5~1.5 → edge-tts rate 문자열 "-50%"~"+50%"
   */
  _toEdgeRate(val) {
    const pct = Math.round((val - 1.0) * 100);
    return (pct >= 0 ? '+' : '') + pct + '%';
  },

  /**
   * 슬라이더 0.5~1.5 → edge-tts pitch 문자열 "-50Hz"~"+50Hz"
   */
  _toEdgePitch(val) {
    const hz = Math.round((val - 1.0) * 100);
    return (hz >= 0 ? '+' : '') + hz + 'Hz';
  },

  // ========== Browser (Web Speech API) ==========

  /**
   * Browser 모드 재생
   */
  async _playBrowser(processed) {
    if (!this._synth) {
      this._setState('idle');
      return;
    }

    // 음성 로드 대기 (최대 500ms)
    if (!this._voiceLoaded) {
      await new Promise(resolve => {
        const check = () => {
          if (this._voiceLoaded) return resolve();
          setTimeout(check, 50);
        };
        check();
        setTimeout(resolve, 500);
      });
    }

    const sentences = this._splitSentences(processed);
    this._utterances = sentences.map(s => this._createUtterance(s));
    this._currentIdx = 0;

    if (this._utterances.length === 0) {
      this._setState('idle');
      return;
    }

    this._playNextBrowser();
  },

  /**
   * Browser 폴백 직접 재생 (edge 실패 시)
   */
  _playBrowserDirect(text) {
    const sentences = this._splitSentences(text);
    this._utterances = sentences.map(s => this._createUtterance(s));
    this._currentIdx = 0;
    if (this._utterances.length === 0) {
      this._setState('idle');
      return;
    }
    this._playNextBrowser();
  },

  /**
   * SpeechSynthesisUtterance 생성
   */
  _createUtterance(text) {
    const utt = new SpeechSynthesisUtterance(text);
    utt.lang = 'ko-KR';
    utt.rate = this._settings.rate;
    utt.pitch = this._settings.pitch;
    utt.volume = this._settings.volume;
    if (this._voice) {
      utt.voice = this._voice;
    }
    return utt;
  },

  /**
   * Browser 발화 큐 순차 재생
   */
  _playNextBrowser() {
    if (this._currentIdx >= this._utterances.length) {
      this._utterances = [];
      this._currentIdx = 0;
      this._setState('idle');
      return;
    }

    const utt = this._utterances[this._currentIdx];

    utt.onstart = () => {
      if (this._state === 'loading') {
        this._setState('playing');
      }
    };

    utt.onend = () => {
      this._currentIdx++;
      const pause = this._settings.pauseBetween || 0;
      if (pause > 0 && this._currentIdx < this._utterances.length) {
        this._pauseTimer = setTimeout(() => {
          this._pauseTimer = null;
          this._playNextBrowser();
        }, pause);
      } else {
        this._playNextBrowser();
      }
    };

    utt.onerror = (e) => {
      if (e.error === 'canceled' || e.error === 'interrupted') return;
      console.warn('[TTS] 발화 오류:', e.error);
      this._currentIdx++;
      this._playNextBrowser();
    };

    // Safari 워크어라운드
    this._synth.cancel();
    setTimeout(() => {
      this._synth.speak(utt);
    }, 10);
  },

  // ========== 공용 유틸 ==========

  /**
   * 상태 변경 + 콜백
   */
  _setState(newState) {
    this._state = newState;
    if (newState === 'idle') {
      const prevMsgId = this._currentMsgId;
      this._currentMsgId = null;
      if (this.onStateChange) this.onStateChange(prevMsgId, newState);
    } else {
      if (this.onStateChange) this.onStateChange(this._currentMsgId, newState);
    }
  },

  /**
   * 상태 조회
   */
  getState(msgId) {
    if (this._currentMsgId === msgId) return this._state;
    return 'idle';
  },

  /**
   * 문장 분할 (Chrome 15초 끊김 방지 + Edge 문장 단위)
   */
  _splitSentences(text) {
    const raw = text.match(/[^.!?。]+[.!?。]?\s*/g) || [text];
    const result = [];

    for (const s of raw) {
      const trimmed = s.trim();
      if (!trimmed) continue;

      if (trimmed.length <= 200) {
        result.push(trimmed);
      } else {
        const parts = trimmed.split(/[,，]\s*/);
        let buffer = '';
        for (const part of parts) {
          if ((buffer + part).length > 200 && buffer) {
            result.push(buffer.trim());
            buffer = part;
          } else {
            buffer += (buffer ? ', ' : '') + part;
          }
        }
        if (buffer.trim()) result.push(buffer.trim());
      }
    }

    return result.filter(s => s.length > 0);
  },

  /**
   * 캐시 재생 (호환용 — 사용 안 함)
   */
  async playFromCache(ttsId, msgId) {
    // 호환성 유지, 무시
  }
};
