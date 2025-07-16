const uploadArea = document.getElementById('upload-area');
const fileInput = document.getElementById('file-input');
const progressArea = document.getElementById('progress-area');
const uploadedArea = document.getElementById('uploaded-area');

// --- Event Listeners ---
// Make the entire upload area clickable
uploadArea.addEventListener('click', () => fileInput.click());

// --- Upload Queue Logic ---
const uploadQueue = [];
let isUploading = false;

function addToQueue(files) {
    for (const file of files) {
        uploadQueue.push(file);
    }
    processQueue();
}

function processQueue() {
    if (isUploading || uploadQueue.length === 0) {
        return;
    }
    isUploading = true;
    const fileToUpload = uploadQueue.shift();
    uploadFile(fileToUpload).then(() => {
        isUploading = false;
        processQueue();
    });
}

fileInput.addEventListener('change', ({ target }) => {
    const files = target.files;
    if (files.length > 0) {
        progressArea.innerHTML = '';
        uploadedArea.innerHTML = '';
        addToQueue(files);
    }
});

uploadArea.addEventListener('dragover', (event) => {
    event.preventDefault();
    uploadArea.classList.add('active');
});

uploadArea.addEventListener('dragleave', () => {
    uploadArea.classList.remove('active');
});

uploadArea.addEventListener('drop', (event) => {
    event.preventDefault();
    uploadArea.classList.remove('active');
    const files = event.dataTransfer.files;
    if (files.length > 0) {
        progressArea.innerHTML = '';
        uploadedArea.innerHTML = '';
        addToQueue(files);
    }
});

// --- Main Upload Function ---
function uploadFile(file) {
    return new Promise((resolve) => {
        const formData = new FormData();
        formData.append('file', file, file.name);
        
        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/upload', true);

        const fileId = `file-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;

        xhr.upload.onprogress = ({ loaded, total }) => {
            updateProgressBar(file.name, loaded, total, fileId);
        };

        xhr.onload = () => {
            handleUploadCompletion(xhr, file.name, fileId);
            resolve(); // Resolve the promise when upload is complete (success or fail)
        };

        xhr.onerror = () => {
            // Also handle network errors
            handleUploadCompletion(xhr, file.name, fileId);
            resolve();
        };
        
        const initialProgressHTML = `<div class="row" id="progress-${fileId}"></div>`;
        progressArea.insertAdjacentHTML('beforeend', initialProgressHTML);

        xhr.send(formData);
    });
}

// --- File List Logic ---
// The file list is now rendered by the backend.
// We only need the delete functionality and to refresh the page on upload.

function deleteFile(fileId) {
    if (!confirm('Are you sure you want to delete this file? This action cannot be undone.')) {
        return;
    }

    fetch(`/api/files/${fileId}`, {
        method: 'DELETE',
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'ok' || data.status === 'partial_success') {
            console.log(data.message);
            // Remove the file item from the DOM
            const fileItem = document.getElementById(`file-item-${fileId.replace(':', '-')}`);
            if (fileItem) {
                fileItem.remove();
            }
        } else {
            alert('Error deleting file: ' + data.detail);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('An error occurred while deleting the file.');
    });
}

// 在上传成功后也刷新文件列表
function handleUploadCompletion(xhr, originalFileName, fileId) {
    const progressRow = document.getElementById(`progress-${fileId}`);
    if (progressRow) {
        progressRow.remove(); // Remove the progress bar for this file
    }

    let uploadedHTML;
    if (xhr.status === 200) {
        const response = JSON.parse(xhr.responseText);
        const fileUrl = response.url;
        uploadedHTML = `<div class="row" id="uploaded-${fileId}">
                                <div class="content">
                                    <i class="fas fa-check-circle success-icon"></i>
                                    <div class="details">
                                        <span class="name">${originalFileName}</span>
                                        <span class="size"><a href="${fileUrl}" target="_blank" onclick="event.stopPropagation(); copyLink('${fileUrl}'); return false;">${fileUrl}</a></span>
                                    </div>
                                </div>
                                <button class="copy-btn-small" onclick="event.stopPropagation(); copyLink('${fileUrl}');"><i class="fas fa-copy"></i></button>
                            </div>`;
    } else {
        const responseText = xhr.responseText || 'Unknown error';
        let errorMessage = `Upload Failed`;
        try {
            const errorJson = JSON.parse(responseText);
            if (errorJson.detail) {
                errorMessage = errorJson.detail;
            }
        } catch (e) {
            // Not a JSON response, use the raw text if it's not too long
            if (responseText.length < 100) {
                errorMessage = responseText;
            }
        }
        uploadedHTML = `<div class="row error" id="uploaded-${fileId}">
                                <div class="content">
                                    <i class="fas fa-times-circle error-icon"></i>
                                    <div class="details">
                                        <span class="name">${originalFileName}</span>
                                        <span class="size error-message">${errorMessage}</span>
                                    </div>
                                </div>
                            </div>`;
    }
    uploadedArea.insertAdjacentHTML("beforeend", uploadedHTML);
}


// --- UI Helper Functions ---
function updateProgressBar(fileName, loaded, total, fileId) {
    const progressRow = document.getElementById(`progress-${fileId}`);
    if (!progressRow) return;

    let fileLoaded = Math.floor((loaded / total) * 100);
    let progressHTML = `<div class="content">
                            <i class="fas fa-file-alt file-icon"></i>
                            <div class="details">
                                <span class="name">${fileName}</span>
                                <div class="progress-bar">
                                    <div class="progress" style="width: ${fileLoaded}%"></div>
                                </div>
                                <span class="percent">${fileLoaded}%</span>
                            </div>
                        </div>`;
    progressRow.innerHTML = progressHTML;
}

// --- Image Gallery Modal and Actions ---
const modal = document.getElementById("image-modal");
const modalImg = document.getElementById("modal-image");
const captionText = document.getElementById("modal-caption");

function showImageModal(src, alt) {
    if (modal && modalImg && captionText) {
        modal.style.display = "block";
        modalImg.src = src;
        captionText.innerHTML = alt;
    }
}

function closeImageModal() {
    if (modal) {
        modal.style.display = "none";
    }
}

// Close modal when clicking outside the image
window.onclick = function(event) {
    if (event.target == modal) {
        closeImageModal();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // Individual copy button in the list
    const imageListBody = document.querySelector('.image-list-body');
    if (imageListBody) {
        imageListBody.addEventListener('click', function(event) {
            const copyBtn = event.target.closest('.copy-btn');
            if (copyBtn) {
                event.stopPropagation();
                const urlToCopy = copyBtn.dataset.url;
                navigator.clipboard.writeText(urlToCopy).then(() => {
                    showToast('URL copied!');
                    const icon = copyBtn.querySelector('i');
                    icon.classList.remove('fa-copy');
                    icon.classList.add('fa-check');
                    setTimeout(() => {
                        icon.classList.remove('fa-check');
                        icon.classList.add('fa-copy');
                    }, 2000);
                }).catch(err => {
                    console.error('Failed to copy: ', err);
                    showToast('Failed to copy URL.', 'error');
                });
            }
        });
    }
});

function copyLink(filePath) {
    const fullUrl = `${window.location.origin}${filePath}`;
    navigator.clipboard.writeText(fullUrl).then(() => {
        // Optional: Show a notification to the user
        showToast('Link copied to clipboard!');
    }).catch(err => {
        console.error('Failed to copy link: ', err);
        showToast('Failed to copy link.', 'error');
    });
}

// A simple toast notification function
function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.classList.add('show');
    }, 100);
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => {
            document.body.removeChild(toast);
        }, 500);
    }, 3000);
}


// --- Batch Operations & Unified File/Image List Logic ---
document.addEventListener('DOMContentLoaded', () => {
    const selectAllCheckbox = document.getElementById('select-all-checkbox');
    const fileCheckboxes = document.querySelectorAll('.file-checkbox');
    const batchDeleteBtn = document.getElementById('batch-delete-btn');
    const copyLinksBtn = document.getElementById('copy-links-btn');
    const listItems = document.querySelectorAll('.image-list-item, .file-item-disk'); // Unified selector
    const selectionCounter = document.getElementById('selection-counter');
    const formatOptionsContainer = document.querySelector('.link-format-selector');
    const formatOptions = document.querySelectorAll('.format-option');

    // Exit if there's no select-all checkbox on the page.
    if (!selectAllCheckbox) return;

    function updateBatchControls() {
        const selectedCheckboxes = document.querySelectorAll('.file-checkbox:checked');
        const selectedCount = selectedCheckboxes.length;
        const hasSelection = selectedCount > 0;

        if (batchDeleteBtn) batchDeleteBtn.disabled = !hasSelection;
        if (copyLinksBtn) copyLinksBtn.disabled = !hasSelection;

        if (selectionCounter) {
            if (hasSelection) {
                selectionCounter.textContent = `${selectedCount} item(s) selected`;
            } else {
                selectionCounter.textContent = '';
            }
        }

        selectAllCheckbox.checked = selectedCount > 0 && selectedCount === fileCheckboxes.length;

        listItems.forEach(item => {
            const checkbox = item.querySelector('.file-checkbox');
            if (checkbox && checkbox.checked) {
                item.classList.add('selected');
            } else {
                item.classList.remove('selected');
            }
        });
    }

    selectAllCheckbox.addEventListener('change', (event) => {
        fileCheckboxes.forEach(checkbox => {
            checkbox.checked = event.target.checked;
        });
        updateBatchControls();
    });

    fileCheckboxes.forEach(checkbox => {
        checkbox.addEventListener('change', updateBatchControls);
    });

    if (batchDeleteBtn) {
        batchDeleteBtn.addEventListener('click', () => {
            const selectedFiles = document.querySelectorAll('.file-checkbox:checked');
            if (selectedFiles.length === 0) {
                showToast('Please select files to delete.', 'error');
                return;
            }

            if (!confirm(`Are you sure you want to delete ${selectedFiles.length} selected file(s)? This action cannot be undone.`)) {
                return;
            }

            const fileIds = Array.from(selectedFiles).map(cb => cb.dataset.fileId);

            fetch('/api/batch_delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ file_ids: fileIds }),
            })
            .then(response => response.json())
            .then(data => {
                let successCount = 0;
                if (data.deleted) {
                    successCount = data.deleted.length;
                    data.deleted.forEach(fileId => {
                        const fileItem = document.getElementById(`file-item-${fileId.replace(':', '-')}`);
                        if (fileItem) fileItem.remove();
                    });
                }
                showToast(`Successfully deleted ${successCount} file(s).`, 'success');
                
                if (data.failed && data.failed.length > 0) {
                    const failedIds = data.failed.map(f => f.file_id).join(', ');
                    showToast(`Failed to delete: ${failedIds}`, 'error');
                }
                // After deletion, we need to re-query the checkboxes and update controls
                window.location.reload();
            })
            .catch(error => {
                console.error('Error:', error);
                showToast('An error occurred while deleting files.', 'error');
            });
        });
    }

    if (formatOptions.length > 0) {
        formatOptions.forEach(option => {
            option.addEventListener('click', () => {
                formatOptions.forEach(opt => opt.classList.remove('active'));
                option.classList.add('active');
            });
        });
    }

    if (copyLinksBtn) {
        copyLinksBtn.addEventListener('click', () => {
            const selectedFiles = document.querySelectorAll('.file-checkbox:checked');
            if (selectedFiles.length === 0) {
                showToast('Please select files to copy links.', 'error');
                return;
            }

            // Default to 'url' format if format options are not present (e.g., on index.html)
            const activeFormatOption = document.querySelector('.format-option.active');
            const activeFormat = activeFormatOption ? activeFormatOption.dataset.format : 'url';

            const links = Array.from(selectedFiles).map(cb => {
                const listItem = cb.closest('.image-list-item, .file-item-disk');
                const fileUrl = `${window.location.origin}${listItem.dataset.fileUrl}`;
                const fileName = listItem.dataset.filename;

                // Only apply special formats if the options are visible (on image_hosting page)
                if (formatOptionsContainer) {
                    switch (activeFormat) {
                        case 'markdown':
                            return `![${fileName}](${fileUrl})`;
                        case 'html':
                            return `<img src="${fileUrl}" alt="${fileName}">`;
                        case 'ubb':
                            return `[img]${fileUrl}[/img]`;
                        case 'url':
                        default:
                            return fileUrl;
                    }
                }
                // For index.html, always return the direct URL
                return fileUrl;
            });

            navigator.clipboard.writeText(links.join('\n')).then(() => {
                const formatText = formatOptionsContainer ? ` in ${activeFormat.toUpperCase()} format` : '';
                showToast(`${links.length} link(s) copied${formatText}!`, 'success');
            }).catch(err => {
                console.error('Failed to copy links: ', err);
                showToast('Failed to copy links.', 'error');
            });
        });
    }

    updateBatchControls(); // Initial check
});


// --- Real-time file updates using Server-Sent Events (SSE) ---
document.addEventListener('DOMContentLoaded', () => {
    // Only run this logic if we are on a page with a file list
    const fileListDisk = document.getElementById('file-list-disk');
    if (!fileListDisk) {
        return;
    }

    function connectSSE() {
        const eventSource = new EventSource('/api/file-updates');

        eventSource.onmessage = function(event) {
            const file = JSON.parse(event.data);
            addNewFileRow(file);
        };

        eventSource.onerror = function(err) {
            console.error("EventSource failed, will retry in 5 seconds:", err);
            eventSource.close();
            setTimeout(connectSSE, 5000); 
        };

        console.log("SSE connection established for file updates.");
    }

    function addNewFileRow(file) {
        const fileListDisk = document.getElementById('file-list-disk');
        const emptyListMessage = fileListDisk.querySelector('.empty-list');
        
        // If the "empty" message is present, remove it first
        if (emptyListMessage) {
            emptyListMessage.remove();
        }

        const newRow = document.createElement('div');
        newRow.className = 'file-item-disk new-file-fade-in'; // Add animation class
        newRow.id = `file-item-${file.file_id.replace(':', '-')}`;
        newRow.dataset.fileId = file.file_id;
        newRow.dataset.fileUrl = `/d/${file.file_id}`;
        newRow.dataset.filename = file.filename;

        const formattedSize = formatFileSize(file.filesize);
        // Format date to YYYY-MM-DD
        const formattedDate = new Date(file.upload_date).toISOString().split('T')[0];

        newRow.innerHTML = `
            <div class="file-info-checkbox">
                <input type="checkbox" class="file-checkbox" data-file-id="${file.file_id}">
            </div>
            <div class="file-info-disk">
                <i class="fas fa-file-alt file-icon"></i>
                <span class="file-name" title="${file.filename}">${file.filename}</span>
            </div>
            <div class="file-size">${formattedSize}</div>
            <div class="file-date">${formattedDate}</div>
            <div class="file-actions-disk">
                <a href="/d/${file.file_id}" class="action-btn download-btn" title="Download"><i class="fas fa-download"></i></a>
                <button class="action-btn copy-link-btn" title="Copy Link" onclick="copyLink('/d/${file.file_id}')"><i class="fas fa-link"></i></button>
                <button class="action-btn delete-btn" title="Delete" onclick="deleteFile('${file.file_id}')"><i class="fas fa-trash-alt"></i></button>
            </div>
        `;

        fileListDisk.insertBefore(newRow, fileListDisk.firstChild);
        
        // We need to re-initialize event listeners for the new elements,
        // but since the main logic already uses event delegation or runs on DOMContentLoaded,
        // we might only need to update the checkbox logic.
        // For simplicity, we can just re-run the batch control update.
        if (window.updateBatchControls) {
            window.updateBatchControls();
        }
    }

    // Make sure formatFileSize is available
    if (typeof formatFileSize === 'undefined') {
        window.formatFileSize = function(bytes) {
            if (bytes === 0) return '0 Bytes';
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }
    }

    // Start listening for real-time updates
    connectSSE();
});
