/**
 * TTS 엔진 모듈
 * Edge TTS (서버 사이드) + HTML5 Audio 재생
 */
const TTSEngine = {
  _audio: null,
  _currentMsgId: null,  // 현재 재생 중인 메시지 ID
  _state: 'idle',       // idle | loading | playing | paused
  _abortController: null,  // fetch 취소용
  _blobUrl: null,          // ObjectURL 추적용

  // 콜백
  onStateChange: null,  // (msgId, state) => void

  /**
   * TTS 사용 가능 여부
   */
  isAvailable() {
    return true;  // 서버 사이드 TTS이므로 항상 사용 가능
  },

  /**
   * 초기화 (호환성 유지)
   */
  init() {},

  /**
   * 텍스트 재생
   */
  async play(text, msgId) {
    if (!text) return;

    // 다른 메시지 재생 중이면 먼저 정지
    if (this._state !== 'idle') {
      this.stop();
    }

    // 전처리
    const processed = TTSPreprocessor.process(text);
    if (!processed) return;

    this._currentMsgId = msgId;
    this._setState('loading');

    // 이전 fetch 취소
    if (this._abortController) {
      this._abortController.abort();
    }
    this._abortController = new AbortController();

    try {
      // 서버에 TTS 요청
      const response = await fetch(`${API_BASE_URL}/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: processed }),
        signal: this._abortController.signal
      });

      if (!response.ok) {
        throw new Error(`TTS 서버 오류: ${response.status}`);
      }

      // MP3 blob으로 변환 후 재생
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      this._blobUrl = url;

      this._audio = new Audio(url);

      this._audio.onplay = () => {
        this._setState('playing');
      };

      this._audio.onended = () => {
        this._cleanup();
        this._setState('idle');
      };

      this._audio.onerror = (e) => {
        console.warn('[TTS] 재생 오류:', e);
        this._cleanup();
        this._setState('idle');
      };

      await this._audio.play();
    } catch (err) {
      if (err.name === 'AbortError') return;  // 의도적 취소는 무시
      console.warn('[TTS] 요청 실패:', err.message);
      this._cleanup();
      this._setState('idle');
    }
  },

  /**
   * 일시정지
   */
  pause() {
    if (this._state === 'playing' && this._audio) {
      this._audio.pause();
      this._setState('paused');
    }
  },

  /**
   * 재개
   */
  resume() {
    if (this._state === 'paused' && this._audio) {
      this._audio.play();
      this._setState('playing');
    }
  },

  /**
   * 정지
   */
  stop() {
    // 진행 중인 fetch 취소
    if (this._abortController) {
      this._abortController.abort();
      this._abortController = null;
    }
    if (this._audio) {
      this._audio.pause();
      this._audio.currentTime = 0;
    }
    this._cleanup();
    this._setState('idle');
  },

  /**
   * 리소스 정리 (ObjectURL, Audio)
   */
  _cleanup() {
    if (this._blobUrl) {
      URL.revokeObjectURL(this._blobUrl);
      this._blobUrl = null;
    }
    this._audio = null;
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
  }
};
