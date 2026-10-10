document.addEventListener('DOMContentLoaded', () => {
    const preview = document.getElementById('live-preview');
    const status = document.getElementById('live-status');
    const captions = document.getElementById('live-captions');
    const timerEl = document.getElementById('live-timer');
    const goBtn = document.getElementById('go-live-btn');
    const stopBtn = document.getElementById('stop-live-btn');
    const fileWrap = document.getElementById('file-source');
    const fileInput = document.getElementById('live-file');
    const fileName = document.getElementById('live-file-name');

    let ws = null;
    let captureTimer = null;
    let elapsedTimer = null;
    let audioCtx = null;
    let nextPlayTime = 0;
    let currentStream = null;
    let elapsed = 0;

    const checkedValue = (name) => {
        const el = document.querySelector(`input[name="${name}"]:checked`);
        return el ? el.value : null;
    };

    document.querySelectorAll('input[name="live-source"]').forEach((radio) => {
        radio.addEventListener('change', () => {
            fileWrap.style.display = checkedValue('live-source') === 'file' ? 'block' : 'none';
        });
    });

    fileInput.addEventListener('change', () => {
        fileName.textContent = fileInput.files.length ? fileInput.files[0].name : 'No file selected';
        status.textContent = 'Ready to go live!';
        status.style.color = 'var(--orange)';
    });

    preview.addEventListener('ended', () => {
        if (ws) stopBtn.click();
    });

    goBtn.addEventListener('click', async () => {
        if (ws) return;

        const source = checkedValue('live-source');
        const persona = checkedValue('live-persona') || 'play_by_play';

        if (source === 'file' && !fileInput.files.length) {
            alert('Select a video file in the Source card first.');
            return;
        }

        try {
            if (source === 'webcam') {
                currentStream = await navigator.mediaDevices.getUserMedia({ video: { width: 640 } });
                preview.srcObject = currentStream;
                preview.removeAttribute('src');
            } else {
                preview.srcObject = null;
                preview.src = URL.createObjectURL(fileInput.files[0]);
                await preview.play();
            }
        } catch (err) {
            status.textContent = `Could not access ${source === 'webcam' ? 'webcam' : 'video file'}: ${err.message}`;
            return;
        }

        preview.style.display = 'block';
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        nextPlayTime = 0;

        const host = location.host || 'localhost:8000';
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        status.textContent = 'Connecting to the booth...';
        status.style.color = 'var(--dark)';

        ws = new WebSocket(`${proto}://${host}/ws/live`);
        ws.onopen = () => ws.send(JSON.stringify({ type: 'start', persona }));
        ws.onmessage = (e) => {
            try {
                handleServerMessage(JSON.parse(e.data));
            } catch (err) { /* ignore malformed frames */ }
        };
        ws.onerror = () => {
            status.textContent = 'WebSocket error — is the backend running on port 8000?';
        };
        ws.onclose = () => {
            if (ws) finishLive('Disconnected from the booth.');
        };
    });

    stopBtn.addEventListener('click', () => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'stop' }));
        }
        finishLive('Stopped.');
    });

    function handleServerMessage(msg) {
        if (msg.type === 'started') {
            goBtn.style.display = 'none';
            stopBtn.style.display = 'inline-block';
            status.innerHTML = `<strong>🔴 LIVE</strong> — ${msg.voice} on the call`;
            status.style.color = 'var(--orange)';
            captions.style.display = 'block';
            captions.textContent = '';
            startCapture();
            startTimer();
        } else if (msg.type === 'audio') {
            playPcmChunk(msg.data, msg.mime);
        } else if (msg.type === 'transcript') {
            captions.textContent = `"${msg.text}"`;
        } else if (msg.type === 'warning') {
            status.textContent = msg.message;
            status.style.color = '#b8860b';
        } else if (msg.type === 'ended') {
            finishLive(`Session ended (${msg.reason}, ${msg.elapsed_s || 0}s).`);
        } else if (msg.type === 'error') {
            finishLive(`Error: ${msg.message}`);
        }
    }

    function playPcmChunk(b64, mime) {
        const match = /rate=(\d+)/.exec(mime || '');
        const rate = match ? parseInt(match[1], 10) : 24000;

        const bin = atob(b64);
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);

        const nSamples = Math.floor(bytes.length / 2);
        if (!nSamples) return;
        const floats = new Float32Array(nSamples);
        for (let i = 0; i < nSamples; i++) {
            const v = bytes[2 * i] | (bytes[2 * i + 1] << 8);
            floats[i] = (v >= 0x8000 ? v - 0x10000 : v) / 32768;
        }

        const buffer = audioCtx.createBuffer(1, nSamples, rate);
        buffer.copyToChannel(floats, 0);
        const src = audioCtx.createBufferSource();
        src.buffer = buffer;
        src.connect(audioCtx.destination);

        const now = audioCtx.currentTime;
        if (nextPlayTime < now + 0.05) nextPlayTime = now + 0.05;
        src.start(nextPlayTime);
        nextPlayTime += buffer.duration;
    }

    const canvas = document.createElement('canvas');
    const c2d = canvas.getContext('2d');

    function startCapture() {
        captureTimer = setInterval(() => {
            if (!preview.videoWidth) return;
            if (!ws || ws.readyState !== WebSocket.OPEN) return;

            const w = 480;
            const h = Math.round(preview.videoHeight * (w / preview.videoWidth));
            canvas.width = w;
            canvas.height = h;
            c2d.drawImage(preview, 0, 0, w, h);
            const dataUrl = canvas.toDataURL('image/jpeg', 0.7);
            ws.send(JSON.stringify({ type: 'frame', data: dataUrl.split(',')[1] }));
        }, 1000);
    }

    function startTimer() {
        elapsed = 0;
        timerEl.textContent = '0s';
        elapsedTimer = setInterval(() => {
            elapsed += 1;
            timerEl.textContent = `${elapsed}s`;
        }, 1000);
    }

    function finishLive(message) {
        if (captureTimer) { clearInterval(captureTimer); captureTimer = null; }
        if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null; }

        const sock = ws;
        ws = null;
        if (sock) { try { sock.close(); } catch (e) { /* noop */ } }

        if (currentStream) {
            currentStream.getTracks().forEach((t) => t.stop());
            currentStream = null;
        }
        preview.srcObject = null;
        preview.removeAttribute('src');
        preview.style.display = 'none';
        captions.style.display = 'none';

        goBtn.style.display = '';
        stopBtn.style.display = 'none';
        status.textContent = message;
        status.style.color = 'var(--orange)';
    }
});
