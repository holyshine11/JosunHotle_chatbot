/**
 * STT (Speech-to-Text) 엔진 모듈
 * Web Speech API SpeechRecognition 래퍼 (한국어)
 * 크로스 브라우저 지원: Chrome, Whale, Safari, Samsung Internet
 */
const STTEngine = {
  _recognition: null,
  _state: 'idle',  // idle | listening | processing

  // 콜백
  onResult: null,          // (transcript) => void  — 인식 완료 시
  onStateChange: null,     // (state) => void
  onPermissionDenied: null, // () => void  — 마이크 권한 차단 시

  /**
   * 마이크 권한 안내 토스트 표시
   */
  _showPermissionGuide() {
    if (this.onPermissionDenied) {
      this.onPermissionDenied();
      return;
    }
    const el = document.createElement('div');
    el.innerHTML = '🎤 마이크 권한이 필요합니다.<br>주소창 왼쪽 🔒 아이콘 → 사이트 설정 → 마이크 허용';
    el.style.cssText = 'position:fixed;top:80px;left:50%;transform:translateX(-50%);padding:14px 20px;background:#1a365d;color:#fff;font-size:14px;line-height:1.6;border-radius:12px;z-index:99999;box-shadow:0 4px 20px rgba(0,0,0,0.3);max-width:340px;text-align:center;';
    document.body.appendChild(el);
    setTimeout(() => {
      el.style.transition = 'opacity 0.5s';
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 500);
    }, 5000);
  },

  /**
   * STT 사용 가능 여부
   */
  isAvailable() {
    return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
  },

  /**
   * 마이크 권한 확보 (매 호출마다 실행)
   * Whale/Safari 등 일부 브라우저는 getUserMedia로 권한을 먼저 획득해야
   * SpeechRecognition.start()가 정상 동작함
   */
  async _acquireMicPermission() {
    // 1) 표준 API (Chrome, Edge, Safari 등)
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach(track => track.stop());
        return true;
      } catch (err) {
        console.warn('[STT] 마이크 권한 거부 (표준):', err.name, err.message);
        return false;
      }
    }

    // 2) 레거시 API 폴백 (Whale 등 HTTP에서 mediaDevices 미노출 브라우저)
    const legacyGetUserMedia = navigator.getUserMedia
      || navigator.webkitGetUserMedia
      || navigator.mozGetUserMedia
      || navigator.msGetUserMedia;

    if (legacyGetUserMedia) {
      try {
        const stream = await new Promise((resolve, reject) => {
          legacyGetUserMedia.call(navigator, { audio: true }, resolve, reject);
        });
        stream.getTracks().forEach(track => track.stop());
        return true;
      } catch (err) {
        console.warn('[STT] 마이크 권한 거부 (레거시):', err.name || err);
        return false;
      }
    }

    // 3) getUserMedia API 전혀 없는 경우
    //    SpeechRecognition.start()를 시도하되, onerror not-allowed에서 안내 처리
    return true;
  },

  /**
   * 녹음 시작
   */
  async start() {
    if (!this.isAvailable()) return;
    if (this._state !== 'idle') {
      this.stop();
    }

    // 마이크 권한 확보 (Whale/Safari 호환 — 매번 호출)
    const hasPermission = await this._acquireMicPermission();
    if (!hasPermission) {
      this._showPermissionGuide();
      return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    this._recognition = new SpeechRecognition();
    this._recognition.lang = 'ko-KR';
    this._recognition.continuous = false;
    this._recognition.interimResults = false;
    this._recognition.maxAlternatives = 1;

    this._recognition.onstart = () => {
      this._setState('listening');
    };

    this._recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      this._setState('processing');
      if (this.onResult && transcript.trim()) {
        this.onResult(transcript.trim());
      }
      this._setState('idle');
    };

    this._recognition.onerror = (event) => {
      if (event.error !== 'no-speech' && event.error !== 'aborted') {
        console.warn('[STT] 인식 오류:', event.error);
      }
      // 마이크 권한 차단 → 사용자에게 설정 안내
      if (event.error === 'not-allowed') {
        this._showPermissionGuide();
      }
      this._setState('idle');
    };

    this._recognition.onend = () => {
      if (this._state !== 'idle') {
        this._setState('idle');
      }
    };

    // start() 호출 시 예외 처리 (일부 브라우저에서 throw 가능)
    try {
      this._recognition.start();
    } catch (err) {
      console.warn('[STT] start() 예외:', err.message);
      this._recognition = null;
      this._setState('idle');
    }
  },

  /**
   * 녹음 정지
   */
  stop() {
    if (this._recognition) {
      this._recognition.abort();
      this._recognition = null;
    }
    this._setState('idle');
  },

  /**
   * 토글 (시작/정지)
   */
  async toggle() {
    if (this._state === 'idle') {
      await this.start();
    } else {
      this.stop();
    }
  },

  /**
   * 상태 변경
   */
  _setState(newState) {
    this._state = newState;
    if (this.onStateChange) this.onStateChange(newState);
  },

  /**
   * 현재 상태 조회
   */
  getState() {
    return this._state;
  }
};
