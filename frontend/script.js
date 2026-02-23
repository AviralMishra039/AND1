document.addEventListener('DOMContentLoaded', () => {
    const fileInput = document.getElementById('video-upload');
    const fileNameDisplay = document.getElementById('file-name');
    const generateBtn = document.getElementById('generate-card');
    const statusText = document.getElementById('status-text');
    const progressContainer = document.getElementById('progress-container');
    const progressBar = document.getElementById('progress-bar');

    if (fileInput) {
        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                // Get just the filename, not the full path
                const name = e.target.files[0].name;
                fileNameDisplay.textContent = name;
                statusText.textContent = "Ready to generate!";
                statusText.style.color = "var(--orange)";
            } else {
                fileNameDisplay.textContent = "No file selected";
                statusText.textContent = "Click to start AI engine";
                statusText.style.color = "#888";
            }
        });

        generateBtn.addEventListener('click', () => {
            if (fileInput.files.length === 0) {
                alert("Please select a raw basketball video clip in Step 1 first.");
                return;
            }

            // Simulate Generation Process for UI demo until backend is wired
            generateBtn.style.pointerEvents = "none";
            progressContainer.style.display = "block";
            statusText.style.color = "var(--dark)";

            const stages = [
                "1. Uploading video to server...",
                "2. Analyzing Game Momentum...",
                "3. Writing Commentary Script...",
                "4. Generating Audio via Edge-TTS...",
                "5. Assembling Final Video..."
            ];

            let currentStage = 0;

            // Hide previous video if running again
            const outputVideo = document.getElementById('output-video');
            if (outputVideo) outputVideo.style.display = "none";

            // Progress bar simulation up to 90%
            const interval = setInterval(() => {
                if (currentStage < stages.length - 1) {
                    statusText.textContent = stages[currentStage];
                    progressBar.style.width = `${(currentStage + 1) * 20}%`;
                    currentStage++;
                } else {
                    statusText.textContent = stages[4] + " (This takes ~30-60 secs)";
                    progressBar.style.width = "90%";
                    clearInterval(interval);
                }
            }, 1500);

            // Gather Data
            const formData = new FormData();
            formData.append("video_file", fileInput.files[0]);
            const selectedPersona = document.querySelector('input[name="persona"]:checked').value;
            formData.append("persona", selectedPersona);

            // Actual API Call
            fetch("http://localhost:8000/generate", {
                method: "POST",
                body: formData
            })
                .then(response => {
                    if (!response.ok) throw new Error("Backend server error");
                    return response.json(); // Changed to parse JSON
                })
                .then(data => {
                    clearInterval(interval);

                    statusText.innerHTML = "<strong>✅ Process Complete!</strong>";
                    progressBar.style.width = "100%";
                    progressBar.style.background = "#28a745"; // Green success

                    // Display Video
                    if (outputVideo) {
                        outputVideo.src = data.video_url;
                        outputVideo.style.display = "block";
                    }

                    // Display Logs
                    const logsContainer = document.getElementById('logs-container');
                    const scoutLogs = document.getElementById('scout-logs');
                    const writerLogs = document.getElementById('writer-logs');

                    if (logsContainer) {
                        logsContainer.style.display = "block";
                        scoutLogs.textContent = JSON.stringify(data.events, null, 2);
                        writerLogs.textContent = JSON.stringify(data.commentary_segments, null, 2);
                    }

                    setTimeout(() => {
                        generateBtn.style.pointerEvents = "auto";
                        statusText.textContent = "Ready to process another";
                        statusText.style.color = "var(--orange)";
                        progressBar.style.width = "0%";
                        progressContainer.style.display = "none";
                        progressBar.style.background = "var(--orange)";
                    }, 4000);
                })
                .catch(err => {
                    clearInterval(interval);
                    statusText.innerHTML = `<strong>❌ Error:</strong> ${err.message}. Ensure backend is running.`;
                    progressBar.style.background = "red";
                    generateBtn.style.pointerEvents = "auto";
                });
        });

        // Add toggle logic for the logs
        const toggleScout = document.getElementById('toggle-scout');
        const scoutLogs = document.getElementById('scout-logs');
        if (toggleScout && scoutLogs) {
            toggleScout.addEventListener('click', () => {
                scoutLogs.style.display = scoutLogs.style.display === "none" ? "block" : "none";
            });
        }

        const toggleWriter = document.getElementById('toggle-writer');
        const writerLogs = document.getElementById('writer-logs');
        if (toggleWriter && writerLogs) {
            toggleWriter.addEventListener('click', () => {
                writerLogs.style.display = writerLogs.style.display === "none" ? "block" : "none";
            });
        }
    }
});
