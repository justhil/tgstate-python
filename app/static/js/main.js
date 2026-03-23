const uploadArea = document.getElementById('upload-area');
const fileInput = document.getElementById('file-input');
const progressArea = document.getElementById('progress-area');
const uploadedArea = document.getElementById('uploaded-area');
const fileListDisk = document.getElementById('file-list-disk');
const imageListBody = document.getElementById('image-list-body');
const selectAllCheckbox = document.getElementById('select-all-checkbox');
const batchDeleteBtn = document.getElementById('batch-delete-btn');
const copyLinksBtn = document.getElementById('copy-links-btn');
const selectionCounter = document.getElementById('selection-counter');
const formatOptionsContainer = document.querySelector('.link-format-selector');
const formatOptions = document.querySelectorAll('.format-option');

const FILE_ROUTE_PREFIX = '/d';
const uploadQueue = [];
let isUploading = false;

function escapeHtml(value) {
    return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

function isImagePage() {
    return Boolean(imageListBody);
}

function getActiveListContainer() {
    return imageListBody || fileListDisk;
}

function isImageFile(filename) {
    return /\.(jpg|jpeg|png|gif|bmp|webp)$/i.test(filename || '');
}

function buildDownloadPath(fileId, filename) {
    return `${FILE_ROUTE_PREFIX}/${encodeURIComponent(fileId)}/${encodeURIComponent(filename)}`;
}

function getAbsoluteUrl(pathOrUrl) {
    if (/^https?:\/\//i.test(pathOrUrl)) {
        return pathOrUrl;
    }
    return `${window.location.origin}${pathOrUrl}`;
}

function normalizeFilePayload(file) {
    const filename = file.filename || 'unknown';
    const path = file.path || buildDownloadPath(file.file_id, filename);
    return {
        filename,
        file_id: file.file_id,
        filesize: Number(file.filesize || 0),
        upload_date: file.upload_date || new Date().toISOString(),
        path,
        url: file.url || getAbsoluteUrl(path),
    };
}

function getFileItemDomId(fileId) {
    return `file-item-${String(fileId).replaceAll(':', '-')}`;
}

function formatFileSize(bytes) {
    const value = Number(bytes || 0);
    if (value <= 0) {
        return '0 Bytes';
    }

    const units = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
    const decimalPlaces = index === 0 ? 0 : 2;
    return `${(value / (1024 ** index)).toFixed(decimalPlaces)} ${units[index]}`;
}

function formatDisplayDate(rawValue) {
    if (!rawValue) {
        return '';
    }

    const date = new Date(rawValue);
    if (!Number.isNaN(date.getTime())) {
        return date.toISOString().split('T')[0];
    }
    return String(rawValue).split(' ')[0];
}

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
        setTimeout(() => toast.remove(), 500);
    }, 3000);
}

function copyLink(pathOrUrl) {
    const target = getAbsoluteUrl(pathOrUrl);
    navigator.clipboard.writeText(target).then(() => {
        showToast('Link copied to clipboard!');
    }).catch((error) => {
        console.error('Failed to copy link:', error);
        showToast('Failed to copy link.', 'error');
    });
}

window.copyLink = copyLink;

function createIconButton(className, title, iconClass, onClick) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    button.title = title;
    button.innerHTML = `<i class="${iconClass}"></i>`;
    button.addEventListener('click', (event) => {
        event.stopPropagation();
        onClick();
    });
    return button;
}

function createDownloadLink(path) {
    const link = document.createElement('a');
    link.href = path;
    link.className = 'action-btn download-btn';
    link.title = 'Download';
    link.innerHTML = '<i class="fas fa-download"></i>';
    return link;
}

function createCheckbox(fileId, filePath = '') {
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'file-checkbox';
    checkbox.dataset.fileId = fileId;
    if (filePath) {
        checkbox.dataset.fileLink = filePath;
    }
    return checkbox;
}

function ensureEmptyState() {
    const container = getActiveListContainer();
    if (!container) {
        return;
    }

    const realItems = container.querySelectorAll('.file-item-disk, .image-list-item');
    const existingEmpty = container.querySelector('.empty-list');

    if (realItems.length > 0) {
        existingEmpty?.remove();
        return;
    }

    if (existingEmpty) {
        return;
    }

    const empty = document.createElement('div');
    empty.className = 'empty-list';
    if (isImagePage()) {
        empty.innerHTML = '<i class="fas fa-image"></i><p>Your gallery is empty. Upload some images to get started!</p>';
    } else {
        empty.innerHTML = '<i class="fas fa-folder-open"></i><p>No files here. Try uploading something!</p>';
    }
    container.appendChild(empty);
}

function createDiskItem(file) {
    const item = document.createElement('div');
    item.className = 'file-item-disk new-file-fade-in';
    item.id = getFileItemDomId(file.file_id);
    item.dataset.fileId = file.file_id;
    item.dataset.filePath = file.path;
    item.dataset.fileUrl = file.url;
    item.dataset.filename = file.filename;

    const checkboxWrapper = document.createElement('div');
    checkboxWrapper.className = 'file-info-checkbox';
    checkboxWrapper.appendChild(createCheckbox(file.file_id));

    const infoWrapper = document.createElement('div');
    infoWrapper.className = 'file-info-disk';
    infoWrapper.innerHTML = `
        <i class="fas fa-file-alt file-icon"></i>
        <span class="file-name" title="${escapeHtml(file.filename)}">${escapeHtml(file.filename)}</span>
    `;

    const sizeWrapper = document.createElement('div');
    sizeWrapper.className = 'file-size';
    sizeWrapper.textContent = formatFileSize(file.filesize);

    const dateWrapper = document.createElement('div');
    dateWrapper.className = 'file-date';
    dateWrapper.textContent = formatDisplayDate(file.upload_date);

    const actionWrapper = document.createElement('div');
    actionWrapper.className = 'file-actions-disk';
    actionWrapper.appendChild(createDownloadLink(file.path));
    actionWrapper.appendChild(
        createIconButton('action-btn copy-link-btn', 'Copy Link', 'fas fa-link', () => copyLink(file.path))
    );
    actionWrapper.appendChild(
        createIconButton('action-btn delete-btn', 'Delete', 'fas fa-trash-alt', () => deleteFile(file.file_id))
    );

    item.append(checkboxWrapper, infoWrapper, sizeWrapper, dateWrapper, actionWrapper);
    return item;
}

function createImageItem(file) {
    const item = document.createElement('div');
    item.className = 'image-list-item new-file-fade-in';
    item.id = getFileItemDomId(file.file_id);
    item.dataset.fileId = file.file_id;
    item.dataset.filePath = file.path;
    item.dataset.fileUrl = file.url;
    item.dataset.filename = file.filename;

    const checkboxWrapper = document.createElement('div');
    checkboxWrapper.className = 'file-info-checkbox';
    checkboxWrapper.appendChild(createCheckbox(file.file_id, file.path));

    const nameWrapper = document.createElement('div');
    nameWrapper.className = 'file-info-name';

    const image = document.createElement('img');
    image.src = file.path;
    image.alt = file.filename;
    image.className = 'list-thumbnail';
    image.loading = 'lazy';
    image.addEventListener('click', () => showImageModal(file.path, file.filename));

    const name = document.createElement('span');
    name.className = 'file-name';
    name.title = file.filename;
    name.textContent = file.filename;

    nameWrapper.append(image, name);

    const sizeWrapper = document.createElement('div');
    sizeWrapper.className = 'file-info-size';
    sizeWrapper.textContent = formatFileSize(file.filesize);

    const dateWrapper = document.createElement('div');
    dateWrapper.className = 'file-info-date';
    dateWrapper.textContent = formatDisplayDate(file.upload_date);

    const actionWrapper = document.createElement('div');
    actionWrapper.className = 'file-info-actions';
    actionWrapper.appendChild(
        createIconButton('action-btn copy-btn', 'Copy URL', 'fas fa-copy', () => copyLink(file.url))
    );

    const downloadLink = createDownloadLink(file.path);
    downloadLink.setAttribute('download', '');
    actionWrapper.appendChild(downloadLink);

    actionWrapper.appendChild(
        createIconButton('action-btn delete-btn', 'Delete', 'fas fa-trash-alt', () => deleteFile(file.file_id))
    );

    item.append(checkboxWrapper, nameWrapper, sizeWrapper, dateWrapper, actionWrapper);
    return item;
}

function addOrUpdateFileItem(rawFile) {
    if (!rawFile?.file_id || !rawFile?.filename) {
        return;
    }

    const file = normalizeFilePayload(rawFile);
    if (imageListBody && !isImageFile(file.filename)) {
        return;
    }

    const container = getActiveListContainer();
    if (!container) {
        return;
    }

    container.querySelector('.empty-list')?.remove();

    const existing = document.getElementById(getFileItemDomId(file.file_id));
    const nextItem = imageListBody ? createImageItem(file) : createDiskItem(file);

    if (existing) {
        existing.replaceWith(nextItem);
    } else {
        container.insertBefore(nextItem, container.firstChild);
    }

    refreshBatchControls();
}

function removeFileItem(fileId) {
    const item = document.getElementById(getFileItemDomId(fileId));
    if (item) {
        item.remove();
    }

    refreshBatchControls();
    ensureEmptyState();
}

function refreshBatchControls() {
    const checkboxes = Array.from(document.querySelectorAll('.file-checkbox'));
    const selectedCheckboxes = checkboxes.filter((checkbox) => checkbox.checked);
    const selectedCount = selectedCheckboxes.length;
    const hasSelection = selectedCount > 0;

    if (batchDeleteBtn) {
        batchDeleteBtn.disabled = !hasSelection;
    }
    if (copyLinksBtn) {
        copyLinksBtn.disabled = !hasSelection;
    }
    if (selectionCounter) {
        selectionCounter.textContent = hasSelection ? `${selectedCount} item(s) selected` : '';
    }
    if (selectAllCheckbox) {
        selectAllCheckbox.checked = checkboxes.length > 0 && selectedCount === checkboxes.length;
    }

    document.querySelectorAll('.image-list-item, .file-item-disk').forEach((item) => {
        const checkbox = item.querySelector('.file-checkbox');
        item.classList.toggle('selected', Boolean(checkbox?.checked));
    });
}

window.refreshBatchControls = refreshBatchControls;

function updateProgressBar(fileName, loaded, total, fileId) {
    const progressRow = document.getElementById(`progress-${fileId}`);
    if (!progressRow) {
        return;
    }

    const progress = total > 0 ? Math.floor((loaded / total) * 100) : 0;
    progressRow.innerHTML = `
        <div class="content">
            <i class="fas fa-file-alt file-icon"></i>
            <div class="details">
                <span class="name">${escapeHtml(fileName)}</span>
                <div class="progress-bar">
                    <div class="progress" style="width: ${progress}%"></div>
                </div>
                <span class="percent">${progress}%</span>
            </div>
        </div>
    `;
}

function handleUploadCompletion(xhr, originalFileName, fileId, fileSize) {
    const progressRow = document.getElementById(`progress-${fileId}`);
    progressRow?.remove();

    let uploadedHTML;
    if (xhr.status === 200) {
        const response = JSON.parse(xhr.responseText);
        const fileUrl = response.url;
        uploadedHTML = `
            <div class="row" id="uploaded-${fileId}">
                <div class="content">
                    <i class="fas fa-check-circle success-icon"></i>
                    <div class="details">
                        <span class="name">${escapeHtml(originalFileName)}</span>
                        <span class="size"><a href="${fileUrl}" target="_blank">${fileUrl}</a></span>
                    </div>
                </div>
                <button class="copy-btn-small" type="button"><i class="fas fa-copy"></i></button>
            </div>
        `;

        addOrUpdateFileItem({
            file_id: response.file_id,
            filename: response.filename || originalFileName,
            filesize: fileSize,
            upload_date: new Date().toISOString(),
            path: response.path,
            url: response.url,
        });
    } else {
        const responseText = xhr.responseText || 'Unknown error';
        let errorMessage = 'Upload Failed';
        try {
            const errorJson = JSON.parse(responseText);
            errorMessage = errorJson.detail || errorMessage;
        } catch {
            if (responseText.length < 100) {
                errorMessage = responseText;
            }
        }

        uploadedHTML = `
            <div class="row error" id="uploaded-${fileId}">
                <div class="content">
                    <i class="fas fa-times-circle error-icon"></i>
                    <div class="details">
                        <span class="name">${escapeHtml(originalFileName)}</span>
                        <span class="size error-message">${escapeHtml(errorMessage)}</span>
                    </div>
                </div>
            </div>
        `;
    }

    if (uploadedArea) {
        uploadedArea.insertAdjacentHTML('beforeend', uploadedHTML);
        const copyButton = document.querySelector(`#uploaded-${fileId} .copy-btn-small`);
        if (copyButton) {
            copyButton.addEventListener('click', (event) => {
                event.stopPropagation();
                const response = JSON.parse(xhr.responseText);
                copyLink(response.url);
            });
        }
    }
}

function uploadFile(file) {
    return new Promise((resolve) => {
        const formData = new FormData();
        formData.append('file', file, file.name);

        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/upload', true);

        const fileId = `file-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;

        xhr.upload.onprogress = ({ loaded, total }) => {
            updateProgressBar(file.name, loaded, total, fileId);
        };

        xhr.onload = () => {
            handleUploadCompletion(xhr, file.name, fileId, file.size);
            resolve();
        };

        xhr.onerror = () => {
            handleUploadCompletion(xhr, file.name, fileId, file.size);
            resolve();
        };

        if (progressArea) {
            progressArea.insertAdjacentHTML('beforeend', `<div class="row" id="progress-${fileId}"></div>`);
        }

        xhr.send(formData);
    });
}

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
    const nextFile = uploadQueue.shift();
    uploadFile(nextFile).finally(() => {
        isUploading = false;
        processQueue();
    });
}

if (uploadArea && fileInput) {
    uploadArea.addEventListener('click', () => fileInput.click());

    fileInput.addEventListener('change', ({ target }) => {
        const files = target.files;
        if (!files?.length) {
            return;
        }

        if (progressArea) {
            progressArea.innerHTML = '';
        }
        if (uploadedArea) {
            uploadedArea.innerHTML = '';
        }

        addToQueue(files);
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

        const files = event.dataTransfer?.files;
        if (!files?.length) {
            return;
        }

        if (progressArea) {
            progressArea.innerHTML = '';
        }
        if (uploadedArea) {
            uploadedArea.innerHTML = '';
        }

        addToQueue(files);
    });
}

function deleteFile(fileId) {
    if (!confirm('Are you sure you want to delete this file? This action cannot be undone.')) {
        return;
    }

    fetch(`/api/files/${encodeURIComponent(fileId)}`, {
        method: 'DELETE',
    })
        .then(async (response) => {
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                return Promise.reject(data);
            }
            return data;
        })
        .then((data) => {
            removeFileItem(fileId);
            showToast(data.message || `File ${fileId} deleted successfully.`);
        })
        .catch((error) => {
            console.error('Error:', error);
            const errorMessage = error.detail?.message || error.message || 'An error occurred while deleting the file.';
            showToast(errorMessage, 'error');
        });
}

window.deleteFile = deleteFile;

const modal = document.getElementById('image-modal');
const modalImg = document.getElementById('modal-image');
const captionText = document.getElementById('modal-caption');

function showImageModal(src, alt) {
    if (!modal || !modalImg || !captionText) {
        return;
    }

    modal.style.display = 'block';
    modalImg.src = src;
    captionText.textContent = alt;
}

function closeImageModal() {
    if (modal) {
        modal.style.display = 'none';
    }
}

window.showImageModal = showImageModal;
window.closeImageModal = closeImageModal;

window.onclick = function(event) {
    if (event.target === modal) {
        closeImageModal();
    }
};

document.addEventListener('click', (event) => {
    const copyBtn = event.target.closest('.copy-btn');
    if (!copyBtn) {
        return;
    }

    event.stopPropagation();
    const urlToCopy = copyBtn.dataset.url;
    navigator.clipboard.writeText(urlToCopy).then(() => {
        showToast('URL copied!');
        const icon = copyBtn.querySelector('i');
        icon?.classList.remove('fa-copy');
        icon?.classList.add('fa-check');
        setTimeout(() => {
            icon?.classList.remove('fa-check');
            icon?.classList.add('fa-copy');
        }, 2000);
    }).catch((error) => {
        console.error('Failed to copy:', error);
        showToast('Failed to copy URL.', 'error');
    });
});

document.addEventListener('change', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) {
        return;
    }

    if (target.id === 'select-all-checkbox') {
        document.querySelectorAll('.file-checkbox').forEach((checkbox) => {
            checkbox.checked = target.checked;
        });
        refreshBatchControls();
        return;
    }

    if (target.classList.contains('file-checkbox')) {
        refreshBatchControls();
    }
});

formatOptions.forEach((option) => {
    option.addEventListener('click', () => {
        formatOptions.forEach((item) => item.classList.remove('active'));
        option.classList.add('active');
    });
});

if (batchDeleteBtn) {
    batchDeleteBtn.addEventListener('click', () => {
        const selectedFiles = Array.from(document.querySelectorAll('.file-checkbox:checked'));
        if (selectedFiles.length === 0) {
            showToast('Please select files to delete.', 'error');
            return;
        }

        if (!confirm(`Are you sure you want to delete ${selectedFiles.length} selected file(s)? This action cannot be undone.`)) {
            return;
        }

        const fileIds = selectedFiles.map((checkbox) => checkbox.dataset.fileId);
        fetch('/api/batch_delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_ids: fileIds }),
        })
            .then(async (response) => {
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    return Promise.reject(data);
                }
                return data;
            })
            .then((data) => {
                let successCount = 0;
                let failedCount = 0;

                for (const result of data.deleted || []) {
                    removeFileItem(result.file_id);
                    successCount += 1;
                }

                if (data.failed?.length) {
                    failedCount = data.failed.length;
                    const failedMessages = data.failed
                        .map((item) => item.message || `ID: ${item.file_id || 'unknown'}`)
                        .join('\n');
                    console.error('Failed deletions:', failedMessages);
                    showToast(`Failed to delete ${failedCount} file(s).`, 'error');
                }

                if (successCount > 0) {
                    showToast(`Successfully deleted ${successCount} file(s).`, 'success');
                }
                if (successCount === 0 && failedCount === 0) {
                    showToast('No files were deleted.', 'info');
                }
            })
            .catch((error) => {
                console.error('Error:', error);
                showToast('An error occurred while deleting files.', 'error');
            });
    });
}

if (copyLinksBtn) {
    copyLinksBtn.addEventListener('click', () => {
        const selectedFiles = Array.from(document.querySelectorAll('.file-checkbox:checked'));
        if (selectedFiles.length === 0) {
            showToast('Please select files to copy links.', 'error');
            return;
        }

        const activeFormatOption = document.querySelector('.format-option.active');
        const activeFormat = activeFormatOption ? activeFormatOption.dataset.format : 'url';
        const links = selectedFiles.map((checkbox) => {
            const item = checkbox.closest('.image-list-item, .file-item-disk');
            const fileUrl = item?.dataset.fileUrl;
            const fileName = item?.dataset.filename || 'file';

            if (!fileUrl) {
                return '';
            }

            if (formatOptionsContainer) {
                switch (activeFormat) {
                    case 'markdown':
                        return `![${fileName}](${fileUrl})`;
                    case 'html':
                        return `<img src="${fileUrl}" alt="${fileName}">`;
                    case 'ubb':
                        return `[img]${fileUrl}[/img]`;
                    default:
                        return fileUrl;
                }
            }

            return fileUrl;
        }).filter(Boolean);

        navigator.clipboard.writeText(links.join('\n')).then(() => {
            const formatText = formatOptionsContainer ? ` in ${activeFormat.toUpperCase()} format` : '';
            showToast(`${links.length} link(s) copied${formatText}!`, 'success');
        }).catch((error) => {
            console.error('Failed to copy links:', error);
            showToast('Failed to copy links.', 'error');
        });
    });
}

function connectSSE() {
    if (!getActiveListContainer()) {
        return;
    }

    const eventSource = new EventSource('/api/file-updates');
    eventSource.onmessage = (event) => {
        try {
            const payload = JSON.parse(event.data);
            if (payload.action === 'delete') {
                removeFileItem(payload.file_id);
                return;
            }

            if (payload.action === 'add') {
                addOrUpdateFileItem(payload);
            }
        } catch (error) {
            console.error('Failed to parse SSE payload:', error);
        }
    };

    eventSource.onerror = (error) => {
        console.error('EventSource failed, will retry in 5 seconds:', error);
        eventSource.close();
        setTimeout(connectSSE, 5000);
    };
}

document.addEventListener('DOMContentLoaded', () => {
    ensureEmptyState();
    refreshBatchControls();
    connectSSE();
});
