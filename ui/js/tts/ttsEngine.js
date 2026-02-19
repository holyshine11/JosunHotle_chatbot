/**
 * TTS 엔진 모듈
 * Web Speech API (브라우저 내장) 기반
 * - 서버 부하 0, 즉시 재생, 오프라인 동작
 * - 한국어 음성 자동 선택 (Neural 우선)
 * - 긴 텍스트 문장 분할 (Chrome 15초 끊김 방지)
 */
const TTSEngine = {
  _synth: window.speechSynthesis || null,
  _utterances: [],       // 분할된 발화 큐
  _currentIdx: 0,        // 현재 재생 중인 발화 인덱스
  _currentMsgId: null,   // 현재 재생 중인 메시지 ID
  _state: 'idle',        // idle | loading | playing | paused
  _voice: null,          // 선택된 한국어 음성
  _voiceLoaded: false,   // 음성 목록 로드 완료 여부

  // 콜백
  onStateChange: null,  // (msgId, state) => void

  /**
   * TTS 사용 가능 여부
   */
  isAvailable() {
    return !!this._synth;
  },

  /**
   * 초기화: 한국어 음성 선택
   */
  init() {
    if (!this._synth) return;

    const selectVoice = () => {
      const voices = this._synth.getVoices();
      if (!voices.length) return;

      // 한국어 음성 필터
      const koVoices = voices.filter(v => v.lang && v.lang.startsWith('ko'));

      if (koVoices.length > 0) {
        // 우선순위: Neural/Premium > 일반, 여성 우선
        const preferred = koVoices.find(v =>
          /neural|premium|enhanced/i.test(v.name)
        );
        this._voice = preferred || koVoices[0];
      }
      this._voiceLoaded = true;
    };

    // Chrome은 voiceschanged 이벤트로 비동기 로드
    if (this._synth.getVoices().length > 0) {
      selectVoice();
    }
    this._synth.onvoiceschanged = selectVoice;
  },

  /**
   * 텍스트 재생
   */
  async play(text, msgId) {
    if (!text || !this._synth) return;

    // 다른 메시지 재생 중이면 먼저 정지
    if (this._state !== 'idle') {
      this.stop();
    }

    // 전처리
    const processed = TTSPreprocessor.process(text);
    if (!processed) return;

    this._currentMsgId = msgId;
    this._setState('loading');

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

    // 문장 분할 (Chrome 15초 끊김 방지)
    const sentences = this._splitSentences(processed);
    this._utterances = sentences.map(s => this._createUtterance(s));
    this._currentIdx = 0;

    if (this._utterances.length === 0) {
      this._setState('idle');
      return;
    }

    this._playNext();
  },

  /**
   * 캐시 재생 (Web Speech API에서는 직접 텍스트 재생으로 대체)
   */
  async playFromCache(ttsId, msgId) {
    // Web Speech API는 캐시 불필요, 무시
  },

  /**
   * 일시정지
   */
  pause() {
    if (this._state === 'playing' && this._synth) {
      this._synth.pause();
      this._setState('paused');
    }
  },

  /**
   * 재개
   */
  resume() {
    if (this._state === 'paused' && this._synth) {
      this._synth.resume();
      this._setState('playing');
    }
  },

  /**
   * 정지
   */
  stop() {
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
   * 현재 상태 조회
   */
  getState(msgId) {
    if (this._currentMsgId === msgId) return this._state;
    return 'idle';
  },

  /**
   * SpeechSynthesisUtterance 생성
   */
  _createUtterance(text) {
    const utt = new SpeechSynthesisUtterance(text);
    utt.lang = 'ko-KR';
    utt.rate = 1.05;   // 약간 빠르게 (자연스러운 속도)
    utt.pitch = 1.0;
    utt.volume = 1.0;
    if (this._voice) {
      utt.voice = this._voice;
    }
    return utt;
  },

  /**
   * 발화 큐 순차 재생
   */
  _playNext() {
    if (this._currentIdx >= this._utterances.length) {
      // 모든 문장 재생 완료
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
      this._playNext();
    };

    utt.onerror = (e) => {
      if (e.error === 'canceled' || e.error === 'interrupted') return;
      console.warn('[TTS] 발화 오류:', e.error);
      this._currentIdx++;
      this._playNext();
    };

    // Safari 워크어라운드: cancel 후 speak
    this._synth.cancel();
    // 짧은 딜레이로 Safari 안정성 확보
    setTimeout(() => {
      this._synth.speak(utt);
    }, 10);
  },

  /**
   * 문장 분할 (Chrome 15초 끊김 방지)
   * - 마침표/물음표/느낌표 기준 분할
   * - 200자 초과 시 쉼표/공백 기준 추가 분할
   */
  _splitSentences(text) {
    // 1차: 문장 부호 기준 분할
    const raw = text.match(/[^.!?。]+[.!?。]?\s*/g) || [text];
    const result = [];

    for (const s of raw) {
      const trimmed = s.trim();
      if (!trimmed) continue;

      if (trimmed.length <= 200) {
        result.push(trimmed);
      } else {
        // 긴 문장: 쉼표 기준 분할
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
  }
};
