// 自定义宠物配置状态
const customPetState = {
    name: '',
    type: null,
    traits: [],
    catchphrase: '',
    habits: ''
};

// 类型图标映射
const typeIcons = {
    dog: '🐕',
    cat: '🐱',
    rabbit: '🐰',
    bird: '🦜',
    hamster: '🐹',
    fox: '🦊',
    bear: '🐻',
    panda: '🐼'
};

// 类型名称映射
const typeNames = {
    dog: '小狗',
    cat: '小猫',
    rabbit: '小兔',
    bird: '小鸟',
    hamster: '仓鼠',
    fox: '小狐狸',
    bear: '小熊',
    panda: '小熊猫'
};

// DOM 加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    initTypeSelection();
    initPersonalitySelection();
    initCharCounters();
});

// 初始化类型选择
function initTypeSelection() {
    const typeButtons = document.querySelectorAll('.type-btn');
    typeButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            // 移除其他按钮的active状态
            typeButtons.forEach(b => b.classList.remove('active'));
            // 添加当前按钮的active状态
            this.classList.add('active');
            // 更新状态
            customPetState.type = this.dataset.type;
        });
    });
}

// 初始化性格选择
function initPersonalitySelection() {
    const traitButtons = document.querySelectorAll('.personality-btn');
    traitButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            const trait = this.dataset.trait;
            
            if (this.classList.contains('active')) {
                // 取消选择
                this.classList.remove('active');
                customPetState.traits = customPetState.traits.filter(t => t !== trait);
            } else {
                // 最多选择3个性格标签
                if (customPetState.traits.length >= 3) {
                    alert('最多只能选择3个性格标签哦！');
                    return;
                }
                // 添加选择
                this.classList.add('active');
                customPetState.traits.push(trait);
            }
        });
    });
}

// 初始化字符计数器
function initCharCounters() {
    const nameInput = document.getElementById('pet-name');
    const catchphraseInput = document.getElementById('pet-catchphrase');
    const habitsInput = document.getElementById('pet-habits');

    nameInput.addEventListener('input', function() {
        document.getElementById('name-count').textContent = this.value.length;
        customPetState.name = this.value;
    });

    catchphraseInput.addEventListener('input', function() {
        document.getElementById('catchphrase-count').textContent = this.value.length;
        customPetState.catchphrase = this.value;
    });

    habitsInput.addEventListener('input', function() {
        document.getElementById('habits-count').textContent = this.value.length;
        customPetState.habits = this.value;
    });
}

// 返回上一页
function goBack() {
    window.location.href = 'index.html';
}

// 预览宠物配置
function previewPet() {
    // 验证必填项
    if (!validateForm()) {
        return;
    }

    const previewContent = document.getElementById('preview-content');
    const icon = typeIcons[customPetState.type];
    const typeName = typeNames[customPetState.type];

    let html = `
        <div class="preview-card">
            <div class="preview-avatar">${icon}</div>
            <div class="preview-name">${customPetState.name}</div>
            <div class="preview-type">${typeName}</div>
            <div class="preview-traits">
                ${customPetState.traits.map(trait => `<span class="trait-tag">${trait}</span>`).join('')}
            </div>
            ${customPetState.catchphrase ? `<div class="preview-extra">
                <p><strong>口头禅：</strong>${customPetState.catchphrase}</p>
            </div>` : ''}
            ${customPetState.habits ? `<div class="preview-extra">
                <p><strong>特殊习惯：</strong>${customPetState.habits}</p>
            </div>` : ''}
        </div>
    `;

    previewContent.innerHTML = html;
    document.getElementById('preview-modal').style.display = 'flex';
}

// 关闭预览弹窗
function closePreview() {
    document.getElementById('preview-modal').style.display = 'none';
}

// 确认预览后创建
function confirmCreate() {
    closePreview();
    createPet();
}

// 创建宠物
async function createPet() {
    // 验证必填项
    if (!validateForm()) {
        return;
    }

    const loading = document.getElementById('loading');
    loading.style.display = 'flex';

    try {
        const userId = localStorage.getItem('qagent_user_id') || generateUserId();
        
        // 调用API创建自定义宠物
        const petResponse = await API.createCustomPet({
            pet_name: customPetState.name,
            pet_type: customPetState.type,
            personality_tags: customPetState.traits,
            catchphrase: customPetState.catchphrase || undefined,
            special_habits: customPetState.habits || undefined
        });

        // 使用宠物类型 "custom" 和宠物名称创建会话
        const sessionResponse = await API.createSession(userId, 'custom');

        // 保存会话信息
        localStorage.setItem('qagent_session_id', sessionResponse.session_id);
        localStorage.setItem('qagent_pet_type', 'custom');
        localStorage.setItem('qagent_custom_pet_id', petResponse.pet_id);
        localStorage.setItem('qagent_custom_pet_name', customPetState.name);
        localStorage.setItem('qagent_system_prompt', petResponse.system_prompt);
        localStorage.setItem('qagent_welcome', JSON.stringify(petResponse.catchphrase || {}));

        // 跳转到聊天页面
        window.location.href = 'chat.html';
    } catch (error) {
        alert('创建宠物失败，请重试: ' + error.message);
        loading.style.display = 'none';
    }
}

// 验证表单
function validateForm() {
    if (!customPetState.name || customPetState.name.trim() === '') {
        alert('请输入宠物名字！');
        document.getElementById('pet-name').focus();
        return false;
    }

    if (!customPetState.type) {
        alert('请选择宠物类型！');
        return false;
    }

    if (customPetState.traits.length === 0) {
        alert('请至少选择一个性格标签！');
        return false;
    }

    return true;
}

// 生成用户ID
function generateUserId() {
    const userId = 'user_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    localStorage.setItem('qagent_user_id', userId);
    return userId;
}
