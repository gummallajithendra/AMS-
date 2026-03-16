// form_wizard.js
// Handles saving data across 7 pages and submitting the final application

document.addEventListener('DOMContentLoaded', () => {
    // 1. Restore data to form fields from sessionStorage on load
    restoreFormData();

    // 2. Attach blur/change listeners to all inputs to save data as user types
    attachAutoSave();

    // 3. Attach submit listener to the final submit button (only on page 7)
    const submitBtn = document.getElementById('finalSubmitBtn');
    if (submitBtn) {
        submitBtn.addEventListener('click', submitFinalApplication);
    }
});

function getFormId() {
    // Unique key for this session's form progress
    return 'pec_confirm_form_data';
}

function getStoredData() {
    const data = sessionStorage.getItem(getFormId());
    return data ? JSON.parse(data) : {};
}

function saveToStorage(key, value) {
    const data = getStoredData();
    data[key] = value;
    sessionStorage.setItem(getFormId(), JSON.stringify(data));
}

function restoreFormData() {
    const data = getStoredData();
    for (const key in data) {
        let el = document.getElementById(key);
        if (!el) continue;

        const value = data[key];

        if (el.type === 'radio') {
            // For radio: check if this radio's value matches the stored value
            el.checked = (el.value === value);
        } else if (el.type === 'checkbox') {
            el.checked = (value === "true");
        } else if (el.type === 'file') {
            // If it's a file input, we likely stored a base64 string
            // We can't set the file input value, but we can try to find an img preview sibling
            if (value && value.startsWith('data:image')) {
                let imgPreview = el.parentElement.querySelector('img');

                // If img tag doesn't exist (dynamic preview divs), try to find a preview container or create it
                if (!imgPreview) {
                    const previewDiv = el.parentElement.querySelector('div[id*="Preview"]');
                    if (previewDiv) {
                        imgPreview = document.createElement('img');
                        previewDiv.appendChild(imgPreview);
                    } else {
                        imgPreview = document.createElement('img');
                        imgPreview.style.display = 'block';
                        imgPreview.style.maxWidth = '120px';
                        imgPreview.style.marginTop = '10px';
                        el.parentElement.appendChild(imgPreview);
                    }
                }

                if (imgPreview) {
                    imgPreview.src = value;
                    imgPreview.style.display = 'block';

                    // Also hide placeholder if it exists (e.g. in first.html)
                    const placeholder = el.parentElement.querySelector('.photo-placeholder');
                    if (placeholder) placeholder.style.display = 'none';
                }
            }
        } else {
            el.value = value;
        }
    }
}

function attachAutoSave() {
    const inputs = document.querySelectorAll('input, select, textarea');
    inputs.forEach(input => {
        if (input.type === 'file') return;

        // Save initial values that are already present
        if (input.id && input.value && input.type !== 'checkbox' && input.type !== 'radio') {
            saveToStorage(input.id, input.value);
        }

        input.addEventListener('change', (e) => {
            const el = e.target;
            const key = el.id || el.name; // Use name as fallback for files if id is missing
            if (!key) return;

            if (el.type === 'file') {
                const file = el.files[0];
                if (file) {
                    const reader = new FileReader();
                    reader.onload = function (evt) {
                        saveToStorage(key, evt.target.result);
                        // Also try to update preview if it exists
                        const img = el.parentElement.querySelector('img');
                        if (img && !img.src.startsWith('blob:')) {
                            img.src = evt.target.result;
                            img.style.display = 'block';
                        }
                    };
                    reader.readAsDataURL(file);
                }
            } else if (el.type === 'radio') {
                if (el.checked) saveToStorage(key, el.value);
            } else if (el.type === 'checkbox') {
                saveToStorage(key, el.checked ? "true" : "false");
            } else {
                saveToStorage(key, el.value);
            }
        });

        input.addEventListener('input', (e) => {
            const el = e.target;
            const key = el.id;
            if (!key) return;
            if (el.type !== 'checkbox' && el.type !== 'radio') {
                saveToStorage(key, el.value);
            }
        });
    });

    // explicitly save everything right before navigating away to catch dynamically populated fields
    window.addEventListener('beforeunload', () => {
        inputs.forEach(el => {
            const key = el.id;
            if (!key || el.type === 'file') return;

            if (el.type === 'radio') {
                if (el.checked) saveToStorage(key, el.value);
            } else if (el.type === 'checkbox') {
                saveToStorage(key, el.checked ? "true" : "false");
            } else {
                saveToStorage(key, el.value);
            }
        });

        // Push progress to the Database Draft table automatically if application_number exists
        const fullData = getStoredData();
        const appNum = fullData['appNoSearch'];
        if (appNum) {
            const payload = JSON.stringify({
                application_number: appNum,
                form_data: fullData
            });
            // Use sendBeacon as it's guaranteed to fire even as the page unloads
            navigator.sendBeacon('/save_draft', new Blob([payload], { type: 'application/json' }));
        }
    });
}

async function submitFinalApplication() {
    const btn = document.getElementById('finalSubmitBtn');
    if (btn) btn.disabled = true;
    if (btn) btn.innerText = "Submitting...";

    try {
        const fullData = getStoredData();

        // Map stored data to expected backend format
        const payload = {
            form_type: 'confirm',
            application_number: fullData['appNoSearch'] || "", // From page 1
            student_name: fullData['student_name'] || "", // From page 1
            father_name: fullData['father_name'] || "",
            preferred_branch: determineBranch(fullData),
            mobile: fullData['father_mobile'] || "",
            address: fullData['addr_street'] || "",
            form_data: fullData // Keep raw data in form_data json
        };

        console.log("Submitting payload:", payload);
        alert("Debug Payload application_number: " + payload.application_number);

        const response = await fetch('/save_application', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        const res = await response.json();

        if (response.ok && res.success) {
            alert('Application submitted successfully! Application No: ' + res.application_number);
            sessionStorage.removeItem(getFormId()); // clear cache
            window.location.href = '/coordinator_dashboard';
        } else {
            const errorMsg = res.error || "Unknown error";
            alert("Failed to submit application: " + errorMsg);
            if (btn) {
                btn.disabled = false;
                btn.innerText = "Submit";
            }
        }
    } catch (err) {
        console.error("Submission error:", err);
        alert("An error occurred during submission. Check the console.");
        if (btn) {
            btn.disabled = false;
            btn.innerText = "Submit";
        }
    }
}

function determineBranch(data) {
    if (data['prog_CSE'] === "true" || data['prog_CSE'] === "CSE") return "CSE";
    if (data['prog_ECE'] === "true" || data['prog_ECE'] === "ECE") return "ECE";
    if (data['prog_AIDS'] === "true" || data['prog_AIDS'] === "AIDS") return "AIDS";
    if (data['prog_CSBS'] === "true" || data['prog_CSBS'] === "CSBS") return "CSBS";
    if (data['prog_MECH'] === "true" || data['prog_MECH'] === "MECH") return "MECH";
    if (data['prog_CIVIL'] === "true" || data['prog_CIVIL'] === "CIVIL") return "CIVIL";
    // Fallback if checked value was saved weirdly
    return "CSE";
}
