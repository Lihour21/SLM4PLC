/**
 * Ollama4PLC — Frontend Interactions
 */

document.addEventListener('DOMContentLoaded', function() {
    initTheme();
    initToolStatus();
    initFormInteractions();
    initPipelineSteps();
});

// Theme Toggle
function initTheme() {
    const themeToggle = document.getElementById('themeToggle');
    if (!themeToggle) return;

    const savedTheme = localStorage.getItem('ollama4plc-theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);

    themeToggle.addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('ollama4plc-theme', next);
    });
}

// Tool Status Checker
function initToolStatus() {
    checkToolStatus();

    const refreshBtn = document.getElementById('refreshTools');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            refreshBtn.style.animation = 'spin 0.5s ease';
            setTimeout(() => refreshBtn.style.animation = '', 500);
            checkToolStatus();
        });
    }

    // Auto-refresh every 30 seconds
    setInterval(checkToolStatus, 30000);
}

async function checkToolStatus() {
    const tools = ['ollama', 'rusty', 'nuxmv', 'plcverif'];

    for (const tool of tools) {
        const statusEl = document.getElementById(`status-${tool}`);
        if (!statusEl) continue;

        // Show checking state
        statusEl.innerHTML = `<span class="status-dot checking"></span><span class="status-text">Checking...</span>`;

        try {
            const response = await fetch(`/api/health/${tool}`, { method: 'GET' });
            const data = await response.json();

            if (data.status === 'ok') {
                statusEl.innerHTML = `<span class="status-dot online"></span><span class="status-text">Online</span>`;
            } else {
                statusEl.innerHTML = `<span class="status-dot offline"></span><span class="status-text">Offline</span>`;
            }
        } catch (e) {
            statusEl.innerHTML = `<span class="status-dot offline"></span><span class="status-text">Offline</span>`;
        }
    }
}

// Form Interactions
function initFormInteractions() {
    const form = document.getElementById('pipelineForm');
    const submitBtn = document.getElementById('submitBtn');
    const reqTextarea = document.getElementById('requirements');
    const propTextarea = document.getElementById('plcverif_properties');
    const charCount = document.getElementById('reqCharCount');
    const clearBtn = document.getElementById('clearRequirements');
    const loadExampleBtn = document.getElementById('loadExample');
    const toggleHintBtn = document.getElementById('togglePropertiesHint');
    const hintBox = document.getElementById('propertiesHint');

    // Character count
    if (reqTextarea && charCount) {
        const updateCount = () => {
            charCount.textContent = `${reqTextarea.value.length} chars`;
        };
        reqTextarea.addEventListener('input', updateCount);
        updateCount();
    }

    // Clear button
    if (clearBtn && reqTextarea) {
        clearBtn.addEventListener('click', () => {
            reqTextarea.value = '';
            reqTextarea.focus();
            if (charCount) charCount.textContent = '0 chars';
        });
    }

    // Load example
    if (loadExampleBtn && reqTextarea) {
        loadExampleBtn.addEventListener('click', () => {
            reqTextarea.value = `Create ST code for a conveyor belt control system.
Inputs: Start_Button, Stop_Button, Emergency_Stop, Item_Sensor
Outputs: Conveyor_Motor, Alarm_Horn, Item_Count
Logic:
- Start_Button starts the conveyor
- Stop_Button or Emergency_Stop stops it
- Item_Sensor increments counter on rising edge
- Alarm sounds if Emergency_Stop pressed`;
            if (charCount) charCount.textContent = `${reqTextarea.value.length} chars`;
            reqTextarea.focus();
        });
    }

    // Toggle properties hint
    if (toggleHintBtn && hintBox) {
        toggleHintBtn.addEventListener('click', () => {
            hintBox.classList.toggle('visible');
        });
    }

    // Form submission with loading state
    if (form && submitBtn) {
        form.addEventListener('submit', () => {
            submitBtn.classList.add('loading');
            submitBtn.querySelector('.btn-text').textContent = 'Processing';
        });
    }
}

// Pipeline Step Interactions
function initPipelineSteps() {
    const steps = document.querySelectorAll('.timeline-step');

    steps.forEach(step => {
        const header = step.querySelector('.step-header-row');
        if (!header) return;

        header.style.cursor = 'pointer';
        header.addEventListener('click', () => {
            step.classList.toggle('expanded');
        });
    });
}

// Copy Code Function
function copyCode(btn) {
    const codeBlock = btn.closest('.code-panel').querySelector('code');
    if (!codeBlock) return;

    navigator.clipboard.writeText(codeBlock.textContent).then(() => {
        const original = btn.innerHTML;
        btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>`;
        btn.style.color = 'var(--accent-green)';

        setTimeout(() => {
            btn.innerHTML = original;
            btn.style.color = '';
        }, 2000);
    });
}

// Add spin animation for refresh button
const style = document.createElement('style');
style.textContent = `
    @keyframes spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }
`;
document.head.appendChild(style);
