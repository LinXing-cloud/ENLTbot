// 通用JavaScript功能

// 页面加载完成后的初始化
document.addEventListener('DOMContentLoaded', function() {
    // 自动隐藏警告消息
    setTimeout(function() {
        const alerts = document.querySelectorAll('.alert');
        alerts.forEach(function(alert) {
            alert.style.transition = 'opacity 0.5s';
            alert.style.opacity = '0';
            setTimeout(function() {
                alert.style.display = 'none';
            }, 500);
        });
    }, 5000);
    
    // 表单验证
    const forms = document.querySelectorAll('form');
    forms.forEach(function(form) {
        form.addEventListener('submit', function(event) {
            const requiredFields = form.querySelectorAll('[required]');
            let valid = true;
            
            requiredFields.forEach(function(field) {
                if (!field.value.trim()) {
                    valid = false;
                    field.style.borderColor = '#e74c3c';
                    
                    // 添加错误提示
                    let errorMsg = field.nextElementSibling;
                    if (!errorMsg || !errorMsg.classList.contains('error-message')) {
                        errorMsg = document.createElement('div');
                        errorMsg.className = 'error-message';
                        errorMsg.style.color = '#e74c3c';
                        errorMsg.style.fontSize = '0.8rem';
                        errorMsg.style.marginTop = '0.25rem';
                        errorMsg.textContent = '此字段不能为空';
                        field.parentNode.appendChild(errorMsg);
                    }
                } else {
                    field.style.borderColor = '';
                    
                    // 移除错误提示
                    const errorMsg = field.nextElementSibling;
                    if (errorMsg && errorMsg.classList.contains('error-message')) {
                        errorMsg.remove();
                    }
                }
            });
            
            if (!valid) {
                event.preventDefault();
            }
        });
    });
    
    // 密码强度检查
    const passwordFields = document.querySelectorAll('input[type="password"]');
    passwordFields.forEach(function(field) {
        field.addEventListener('input', function() {
            const password = field.value;
            const strength = checkPasswordStrength(password);
            
            // 移除现有的强度指示器
            const existingIndicator = field.parentNode.querySelector('.password-strength');
            if (existingIndicator) {
                existingIndicator.remove();
            }
            
            // 添加强度指示器
            if (password.length > 0) {
                const indicator = document.createElement('div');
                indicator.className = 'password-strength';
                indicator.style.marginTop = '0.25rem';
                indicator.style.fontSize = '0.8rem';
                
                let message = '';
                let color = '';
                
                switch(strength) {
                    case 0:
                        message = '密码太弱';
                        color = '#e74c3c';
                        break;
                    case 1:
                        message = '密码较弱';
                        color = '#e67e22';
                        break;
                    case 2:
                        message = '密码中等';
                        color = '#f1c40f';
                        break;
                    case 3:
                        message = '密码强';
                        color = '#27ae60';
                        break;
                    case 4:
                        message = '密码非常强';
                        color = '#2ecc71';
                        break;
                }
                
                indicator.textContent = message;
                indicator.style.color = color;
                field.parentNode.appendChild(indicator);
            }
        });
    });
});

// 检查密码强度
function checkPasswordStrength(password) {
    let strength = 0;
    
    // 长度检查
    if (password.length >= 8) strength++;
    if (password.length >= 12) strength++;
    
    // 包含小写字母
    if (/[a-z]/.test(password)) strength++;
    
    // 包含大写字母
    if (/[A-Z]/.test(password)) strength++;
    
    // 包含数字
    if (/[0-9]/.test(password)) strength++;
    
    // 包含特殊字符
    if (/[^a-zA-Z0-9]/.test(password)) strength++;
    
    // 限制最大强度为4
    return Math.min(strength, 4);
}

// 显示加载动画
function showLoading(button) {
    if (button) {
        const originalText = button.textContent;
        button.innerHTML = '<span class="loading-spinner"></span> 处理中...';
        button.disabled = true;
        return originalText;
    }
    return '';
}

// 隐藏加载动画
function hideLoading(button, originalText) {
    if (button && originalText) {
        button.textContent = originalText;
        button.disabled = false;
    }
}

// 创建加载动画样式
const style = document.createElement('style');
style.textContent = `
.loading-spinner {
    display: inline-block;
    width: 1rem;
    height: 1rem;
    border: 2px solid #f3f3f3;
    border-top: 2px solid #3498db;
    border-radius: 50%;
    animation: spin 1s linear infinite;
}

@keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}
`;
document.head.appendChild(style);

// 复制到剪贴板
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(function() {
        alert('已复制到剪贴板');
    }).catch(function(err) {
        console.error('复制失败: ', err);
        // 备选方案
        const textArea = document.createElement('textarea');
        textArea.value = text;
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
        alert('已复制到剪贴板');
    });
}