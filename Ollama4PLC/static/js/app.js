/**
 * Ollama4PLC - Modern Web Application
 * Interactive frontend with real-time pipeline visualization
 */

document.addEventListener('DOMContentLoaded', () => {
    initApp();
});

function initApp() {
    initTheme();
    initFormHandling();
    initAnimations();
    initCodeHighlighting();
    initTooltips();
}

// ===== THEME MANAGEMENT =====
function initTheme() {
    const themeToggle = document.getElementById('theme-toggle');
    const savedTheme = localStorage.getItem('ollama4plc-theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);

    if (themeToggle) {
        themeToggle.addEventListener('click', () => {
            const current = document.documentElement.getAttribute('data-theme');
            const next = current === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', next);
            localStorage.setItem('ollama4plc-theme', next);
            updateThemeIcon(next);
        });
        updateThemeIcon(savedTheme);
    }
}

function updateThemeIcon(theme) {
    const icon = document.querySelector('#theme-toggle .theme-icon');
    if (icon) {
        icon.textContent = theme === 'dark' ? '☀️' : '🌙';
    }
}

// ===== FORM HANDLING =====
function initFormHandling() {
    const form = document.getElementById('pipeline-form');
    const requirementsArea = document.getElementById('requirements');
    const charCount = document.getElementById('char-count');
    const submitBtn = document.getElementById('submit-btn');

    if (requirementsArea && charCount) {
        requirementsArea.addEventListener('input', () => {
            const len = requirementsArea.value.length;
            charCount.textContent = `${len} chars`;
            charCount.classList.toggle('warning', len > 2000);
        });
    }

    if (form) {
        form.addEventListener('submit', (e) => {
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.innerHTML = `
                    <span class="spinner"></span>
                    <span>Processing Pipeline...</span>
                `;
            }

            // Show pipeline animation
            showPipelineLoading();
        });
    }

    // Example buttons
    document.querySelectorAll('.example-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const example = btn.dataset.example;
            loadExample(example);
        });
    });

    // Property templates
    document.querySelectorAll('.property-template').forEach(btn => {
        btn.addEventListener('click', () => {
            const template = btn.dataset.template;
            insertPropertyTemplate(template);
        });
    });
}

function showPipelineLoading() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) {
        overlay.classList.add('active');
        animatePipelineSteps();
    }
}

function animatePipelineSteps() {
    const steps = document.querySelectorAll('.pipeline-step');
    let current = 0;

    function activateNext() {
        if (current < steps.length) {
            steps.forEach((s, i) => {
                s.classList.remove('active', 'completed');
                if (i < current) s.classList.add('completed');
                if (i === current) s.classList.add('active');
            });
            current++;
            setTimeout(activateNext, 2500 + Math.random() * 2000);
        }
    }

    activateNext();
}

function loadExample(type) {
    const requirementsArea = document.getElementById('requirements');
    const propertiesArea = document.getElementById('plcverif_properties');

    const examples = {
        motor: {
            req: `Create ST code for a simple start/stop motor control.
Inputs: Start_PB, Stop_PB. Outputs: Motor_Run.
Logic: Pressing Start_PB turns on Motor_Run, which stays on until Stop_PB is pressed.`,
            prop: `(*! LTL G (Motor_Run -> F !Stop_PB) *)
(*! LTL G !(Motor_Run & Stop_PB) *)`
        },
        traffic: {
            req: `Create a traffic light controller with 3 states.
Inputs: Enable, Emergency_Stop.
Outputs: Red_Light, Yellow_Light, Green_Light.
Cycle: Red 5s, Green 2s, Yellow 1s.`,
            prop: `(*! LTL G !(Red_Light & Green_Light) *)
(*! LTL G (Emergency_Stop -> F !Enable) *)`
        },
        conveyor: {
            req: `Create a conveyor belt control system.
Inputs: Start_Button, Stop_Button, Item_Detected, Emergency_Stop.
Outputs: Conveyor_Motor, Alarm_Horn, Counter_Value.
Logic: Start/Stop control with item counting and emergency stop.`,
            prop: `(*! LTL G (Emergency_Stop -> F !Conveyor_Motor) *)
(*! LTL G (Conveyor_Motor -> Counter_Value >= 0) *)`
        }
    };

    const ex = examples[type];
    if (ex && requirementsArea) {
        requirementsArea.value = ex.req;
        requirementsArea.dispatchEvent(new Event('input'));

        // Animate the fill
        requirementsArea.style.transition = 'none';
        requirementsArea.style.background = 'var(--accent-glow)';
        setTimeout(() => {
            requirementsArea.style.transition = 'background 0.5s ease';
            requirementsArea.style.background = '';
        }, 100);
    }

    if (ex && propertiesArea) {
        propertiesArea.value = ex.prop;
    }
}

function insertPropertyTemplate(template) {
    const area = document.getElementById('plcverif_properties');
    if (!area) return;

    const templates = {
        safety: `(*! LTL G !(Output1 & Output2) *)`,
        liveness: `(*! LTL G (Input -> F Output) *)`,
        invariant: `(*! LTL G (Variable >= 0) *)`,
        implication: `(*! LTL G (Condition -> F Result) *)`
    };

    const current = area.value;
    const insert = templates[template] || '';
    area.value = current ? current + '\n' + insert : insert;
    area.focus();
}

// ===== ANIMATIONS =====
function initAnimations() {
    // Intersection observer for scroll animations
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('animate-in');
            }
        });
    }, { threshold: 0.1 });

    document.querySelectorAll('.animate-on-scroll').forEach(el => {
        observer.observe(el);
    });

    // Stagger animation for cards
    document.querySelectorAll('.stagger-children').forEach(parent => {
        const children = parent.children;
        Array.from(children).forEach((child, i) => {
            child.style.animationDelay = `${i * 0.1}s`;
        });
    });
}

// ===== CODE HIGHLIGHTING =====
function initCodeHighlighting() {
    document.querySelectorAll('pre code').forEach(block => {
        highlightSTCode(block);
    });
}

function highlightSTCode(element) {
    let html = element.innerHTML;

    // ST keywords
    const keywords = [
        'PROGRAM', 'END_PROGRAM', 'VAR', 'VAR_INPUT', 'VAR_OUTPUT', 'END_VAR',
        'IF', 'THEN', 'ELSE', 'ELSIF', 'END_IF', 'CASE', 'OF', 'END_CASE',
        'FOR', 'TO', 'BY', 'DO', 'END_FOR', 'WHILE', 'END_WHILE', 'REPEAT',
        'UNTIL', 'END_REPEAT', 'EXIT', 'RETURN', 'FUNCTION', 'END_FUNCTION',
        'FUNCTION_BLOCK', 'END_FUNCTION_BLOCK', 'AND', 'OR', 'NOT', 'XOR',
        'MOD', 'TRUE', 'FALSE', 'BOOL', 'INT', 'REAL', 'STRING', 'TIME',
        'ARRAY', 'STRUCT', 'END_STRUCT', 'TYPE', 'END_TYPE'
    ];

    keywords.forEach(kw => {
        const regex = new RegExp(`\b${kw}\b`, 'gi');
        html = html.replace(regex, `<span class="kw">${kw}</span>`);
    });

    // Comments
    html = html.replace(
        /(\(\*.*?\*\))/g,
        '<span class="comment">$1</span>'
    );

    // Strings
    html = html.replace(
        /('.*?')/g,
        '<span class="string">$1</span>'
    );

    // Numbers
    html = html.replace(
        /(\d+)/g,
        '<span class="number">$1</span>'
    );

    // Assignment
    html = html.replace(
        /(:=)/g,
        '<span class="operator">$1</span>'
    );

    element.innerHTML = html;
}

// ===== TOOLTIPS =====
function initTooltips() {
    document.querySelectorAll('[data-tooltip]').forEach(el => {
        el.addEventListener('mouseenter', (e) => {
            showTooltip(e, el.dataset.tooltip);
        });
        el.addEventListener('mouseleave', hideTooltip);
    });
}

function showTooltip(e, text) {
    const tooltip = document.createElement('div');
    tooltip.className = 'tooltip';
    tooltip.textContent = text;
    document.body.appendChild(tooltip);

    const rect = e.target.getBoundingClientRect();
    tooltip.style.left = `${rect.left + rect.width / 2 - tooltip.offsetWidth / 2}px`;
    tooltip.style.top = `${rect.top - tooltip.offsetHeight - 8}px`;

    requestAnimationFrame(() => tooltip.classList.add('show'));
}

function hideTooltip() {
    const tooltip = document.querySelector('.tooltip');
    if (tooltip) tooltip.remove();
}

// ===== COPY TO CLIPBOARD =====
function copyToClipboard(text, btn) {
    navigator.clipboard.writeText(text).then(() => {
        const original = btn.innerHTML;
        btn.innerHTML = '✅ Copied!';
        btn.classList.add('copied');
        setTimeout(() => {
            btn.innerHTML = original;
            btn.classList.remove('copied');
        }, 2000);
    });
}

// ===== PIPELINE STEP TOGGLE =====
function toggleStep(stepId) {
    const step = document.getElementById(stepId);
    if (step) {
        step.classList.toggle('collapsed');
    }
}

// ===== CONFETTI FOR SUCCESS =====
function celebrateSuccess() {
    const colors = ['#10b981', '#3b82f6', '#8b5cf6', '#f59e0b', '#ef4444'];
    for (let i = 0; i < 50; i++) {
        setTimeout(() => {
            const confetti = document.createElement('div');
            confetti.className = 'confetti';
            confetti.style.left = Math.random() * 100 + 'vw';
            confetti.style.background = colors[Math.floor(Math.random() * colors.length)];
            confetti.style.animationDuration = (Math.random() * 2 + 1) + 's';
            document.body.appendChild(confetti);
            setTimeout(() => confetti.remove(), 3000);
        }, i * 30);
    }
}

// ===== RESULTS PAGE INIT =====
if (document.querySelector('.results-page')) {
    document.addEventListener('DOMContentLoaded', () => {
        initCodeHighlighting();

        // Animate steps appearing
        const steps = document.querySelectorAll('.pipeline-result-step');
        steps.forEach((step, i) => {
            step.style.opacity = '0';
            step.style.transform = 'translateY(20px)';
            setTimeout(() => {
                step.style.transition = 'all 0.5s ease';
                step.style.opacity = '1';
                step.style.transform = 'translateY(0)';
            }, i * 200);
        });

        // Celebrate if success
        const statusBanner = document.querySelector('.status-success');
        if (statusBanner) {
            setTimeout(celebrateSuccess, 500);
        }
    });
}
