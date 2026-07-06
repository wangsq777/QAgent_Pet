class ChatApp {
    constructor() {
        this.sessionId = localStorage.getItem('qagent_session_id');
        this.petType = localStorage.getItem('qagent_pet_type');
        this.petTypeEmoji = localStorage.getItem('qagent_pet_type_emoji') || '🐾';
        this.welcomeMessage = JSON.parse(localStorage.getItem('qagent_welcome') || '{}');
        this.intimacy = parseInt(localStorage.getItem('qagent_intimacy') || '0');
        this.messages = [];
        this.isLoading = false;
        
        this.init();
    }

    init() {
        if (!this.sessionId) {
            alert('请先选择宠物！');
            window.location.href = 'index.html';
            return;
        }

        this.currentVisitId = null;
        this.visitHostName = '';
        this.visitGuestName = '';
        this.visitIsLoading = false;

        this.renderPetInfo();
        this.updateIntimacy(this.intimacy);
        this.loadHistoryMessages();
        this.loadPetStatus();
        this.bindEvents();
        this.initVisitFeature();
    }

    // 宠物类型对应的 emoji
    getPetEmoji(petType) {
        const emojis = {
            'hot_dog': '🐕',
            'cold_cat': '🐱',
            'mouse': '🐹',
            'dog': '🐕',
            'cat': '🐱',
            'hamster': '🐹',
            'panda': '🐼',
            'tiger': '🐯',
            'lion': '🦁',
            'snake': '🐍',
            'cheetah': '🐆',
            'deer': '🦌',
            'lamb': '🐑',
            'pig': '🐷',
            'horse': '🐴',
            'rabbit': '🐰',
            'bird': '🐦',
            'fox': '🦊',
            'bear': '🐻'
        };
        return emojis[petType] || '🐾';
    }

    // 宠物类型对应的预置头像图片路径
    getPetPresetImage(petType) {
        const presets = {
            'hot_dog': 'images/hot_dog.png',
            'cold_cat': 'images/cold_cat.png',
            'mouse': 'images/mouse.png',
            'dog': 'images/hot_dog.png',
            'cat': 'images/cold_cat.png',
            'hamster': 'images/mouse.png',
            'panda': 'images/panda.png',
            'tiger': 'images/tiger.png',
            'lion': 'images/lion.png',
            'snake': 'images/snake.png',
            'cheetah': 'images/cheetah.png',
            'deer': 'images/deer.png',
            'lamb': 'images/lamb.png',
            'pig': 'images/pig.png',
            'horse': 'images/horse.png'
        };
        return presets[petType] || '';
    }

    // 宠物类型对应的颜色
    getPetColor(petType) {
        const colors = {
            'hot_dog': '#ff6b6b',
            'cold_cat': '#74b9ff',
            'mouse': '#fdcb6e',
            'dog': '#ff6b6b',
            'cat': '#74b9ff',
            'hamster': '#fdcb6e',
            'panda': '#000000',
            'tiger': '#ff9f43',
            'lion': '#feca57',
            'snake': '#26de81',
            'cheetah': '#eb3b5a',
            'deer': '#a55eea',
            'lamb': '#dfe6e9',
            'pig': '#fab1a0',
            'horse': '#8e44ad',
            'rabbit': '#fd79a8',
            'bird': '#00cec9',
            'fox': '#e17055',
            'bear': '#cd6133'
        };
        return colors[petType] || '#a29bfe';
    }

    renderPetInfo() {
        const petNames = {
            'hot_dog': 'Hot Dog',
            'cold_cat': 'Cold Cat',
            'mouse': '鼠鼠',
            'custom': localStorage.getItem('qagent_custom_pet_name') || '我的宠物'
        };

        const petName = petNames[this.petType] || localStorage.getItem('qagent_custom_pet_name') || '我的宠物';
        const isCustom = this.petType === 'custom';
        const customAvatar = isCustom ? localStorage.getItem('qagent_custom_avatar') : null;
        
        // 获取自定义宠物的原始 pet_type（dog/cat/hamster 等），用于查找预置图和颜色
        let rawPetType = '';
        if (isCustom) {
            try {
                const stored = localStorage.getItem('qagent_custom_pet');
                rawPetType = stored ? JSON.parse(stored).pet_type : '';
            } catch(e) {}
        }
        
        const petEmoji = this.getPetEmoji(isCustom ? rawPetType : this.petType);
        const petColor = this.getPetColor(isCustom ? rawPetType : this.petType);
        
        // 设置宠物名称
        document.getElementById('pet-name').textContent = petName;
        
        // 设置宠物头像（自定义宠物: 自定义头像 > 按 pet_type 查预置图 > emoji；内置宠物: 预置图片 > emoji）
        const petEmojiEl = document.getElementById('pet-emoji');
        let avatarSet = false;
        
        if (customAvatar) {
            petEmojiEl.innerHTML = `<img src="${customAvatar}" alt="${petName}" class="pet-avatar-img" style="width: 70px; height: 70px; object-fit: cover; border-radius: 50%;">`;
            avatarSet = true;
        }
        
        if (!avatarSet) {
            // 对于内置宠物，直接用 petType 查预置图；对于自定义宠物，用 rawPetType 查预置图
            const lookupType = isCustom ? rawPetType : this.petType;
            const presetImg = this.getPetPresetImage(lookupType);
            if (presetImg) {
                petEmojiEl.innerHTML = `<img src="${presetImg}" alt="${petName}" class="pet-avatar-img" style="width: 70px; height: 70px; object-fit: cover; border-radius: 50%;">`;
            } else {
                petEmojiEl.innerHTML = `<span class="pet-emoji-text">${petEmoji}</span>`;
            }
        }
        
        document.getElementById('pet-color').style.background = petColor;
        document.getElementById('pet-color').textContent = petName;
        document.getElementById('header-pet-name').textContent = petName;
        document.documentElement.style.setProperty('--pet-accent', petColor);
        document.documentElement.style.setProperty('--pet-accent-soft', this.hexToRgba(petColor, 0.16));
    }

    loadWelcomeMessage() {
        if (this.welcomeMessage && this.welcomeMessage.content) {
            this.addMessage({
                role: 'assistant',
                content: this.welcomeMessage.content,
                is_proactive: true,
                created_at: this.welcomeMessage.created_at || new Date().toISOString()
            });
        }
    }

    async loadHistoryMessages() {
        try {
            // 同时获取消息、会话详情、记忆面板以同步所有数据
            const [messagesResponse, sessionResponse, memoryData] = await Promise.all([
                API.getMessages(this.sessionId),
                API.getSession(this.sessionId),
                API.getMemoryPanel(this.sessionId)
            ]);
            
            // 从后端同步亲密度和累计对话到侧边栏
            this.updateIntimacy(sessionResponse.intimacy);
            this.updateTotalChats(memoryData.total_chats);
            this.loadPetStatus();
            
            const response = messagesResponse;
            // 检查历史消息中是否已有欢迎消息（由后端 create_session 保存的）
            const hasWelcomeMsg = response.messages.some(
                msg => msg.role === 'assistant' && msg.is_proactive
            );

            response.messages.forEach(msg => {
                if (msg.role !== 'system') {
                    this.addMessage(msg);
                }
            });

            // 如果历史消息中没有欢迎消息，才从 localStorage 显示
            // 这样避免重复显示欢迎消息
            if (!hasWelcomeMsg && this.welcomeMessage?.content) {
                this.loadWelcomeMessage();
            }
        } catch (error) {
            console.error('加载历史消息失败:', error);
            // 加载失败时，直接显示欢迎消息
            if (this.welcomeMessage?.content) {
                this.loadWelcomeMessage();
            }
        }
    }

    bindEvents() {
        const input = document.getElementById('message-input');
        const sendBtn = document.getElementById('send-btn');

        sendBtn.addEventListener('click', () => this.sendMessage());
        input.addEventListener('input', () => this.autoResizeTextarea(input));
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });
        this.autoResizeTextarea(input);

        document.getElementById('simulate-day').addEventListener('click', () => this.simulateTime('next_day'));
        document.getElementById('simulate-schedule').addEventListener('click', () => this.simulateTime('schedule_trigger'));

        document.getElementById('back-btn').addEventListener('click', () => {
            window.location.href = 'index.html';
        });

        document.getElementById('memory-panel-btn').addEventListener('click', () => this.toggleMemoryPanel());

        const learnBtn = document.getElementById('learn-with-me-btn');
        if (learnBtn) {
            learnBtn.addEventListener('click', () => this.goToLearn());
        }
    }

    /**
     * 跳转到「陪我学」页：预置宠物用 pet_type 作为 pet_id，
     * 自定义宠物用 qagent_custom_pet_id（UUID）。
     */
    goToLearn() {
        const isCustom = this.petType === 'custom';
        const petId = isCustom
            ? localStorage.getItem('qagent_custom_pet_id')
            : this.petType;
        if (!petId) {
            alert('当前宠物信息缺失，请重新选择宠物后再试');
            return;
        }
        window.location.href = `learn.html?pet_id=${encodeURIComponent(petId)}`;
    }

    addMessage(msg) {
        const msgDiv = document.createElement('div');
        const isUser = msg.role === 'user';
        msgDiv.className = `message ${isUser ? 'user-message' : 'pet-message'}`;

        const time = new Date(msg.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
        
        // 获取宠物头像（自定义宠物: 自定义头像 > 按 pet_type 查预置图 > emoji；内置宠物: 预置图片 > emoji）
        const isCustom = this.petType === 'custom';
        let rawPetType = '';
        if (isCustom) {
            try {
                const stored = localStorage.getItem('qagent_custom_pet');
                rawPetType = stored ? JSON.parse(stored).pet_type : '';
            } catch(e) {}
        }
        const petEmoji = this.getPetEmoji(isCustom ? rawPetType : this.petType);
        const customAvatar = isCustom ? localStorage.getItem('qagent_custom_avatar') : null;
        let avatarHtml;
        if (customAvatar) {
            avatarHtml = `<img src="${customAvatar}" alt="宠物" style="width: 36px; height: 36px; object-fit: cover; border-radius: 50%;">`;
        } else {
            const lookupType = isCustom ? rawPetType : this.petType;
            const presetImg = this.getPetPresetImage(lookupType);
            if (presetImg) {
                avatarHtml = `<img src="${presetImg}" alt="宠物" style="width: 36px; height: 36px; object-fit: cover; border-radius: 50%;">`;
            } else {
                avatarHtml = `<span class="pet-emoji-small">${petEmoji}</span>`;
            }
        }
        
        msgDiv.innerHTML = `
            ${!isUser ? `<div class="pet-avatar">${avatarHtml}</div>` : ''}
            <div class="message-content">
                ${msg.is_proactive && !isUser ? '<span class="proactive-tag">主动关怀</span>' : ''}
                <p>${this.escapeHtml(msg.content)}</p>
                <span class="message-time">${time}</span>
            </div>
        `;

        const messagesContainer = document.getElementById('messages-container');
        messagesContainer.appendChild(msgDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;

        this.messages.push(msg);
    }

    async sendMessage() {
        const input = document.getElementById('message-input');
        const content = input.value.trim();

        if (!content || this.isLoading) return;

        this.isLoading = true;
        input.value = '';
        this.autoResizeTextarea(input);
        this.showLoading(true);

        this.addMessage({
            role: 'user',
            content: content,
            created_at: new Date().toISOString()
        });

        try {
            const response = await API.chat(this.sessionId, content);
            
            this.addMessage({
                role: 'assistant',
                content: response.reply,
                created_at: new Date().toISOString()
            });

            // 处理日常分享消息
            if (response.daily_share?.content) {
                this.addMessage({
                    role: 'assistant',
                    content: response.daily_share.content,
                    is_proactive: true,
                    created_at: new Date().toISOString()
                });
            }

            this.updateIntimacy(response.intimacy);
            this.updateTotalChats(response.total_chats);
            this.loadPetStatus();

            if (response.schedule_extracted) {
                this.showNotification(`📅 已记录日程: ${response.schedule_extracted.content}`);
            }

        } catch (error) {
            alert('发送消息失败: ' + error.message);
        } finally {
            this.isLoading = false;
            this.showLoading(false);
        }
    }

    updateIntimacy(intimacy) {
        this.intimacy = intimacy;
        localStorage.setItem('qagent_intimacy', intimacy);
        
        const level = this.getIntimacyLevel(intimacy);
        document.getElementById('intimacy-value').textContent = intimacy;
        document.getElementById('intimacy-level').textContent = level;
        this.syncIntimacyRing(intimacy);
    }

    updateTotalChats(total) {
        document.getElementById('total-chats').textContent = total;
    }

    getIntimacyLevel(intimacy) {
        if (intimacy <= 20) return '陌生';
        if (intimacy <= 50) return '熟悉';
        if (intimacy <= 80) return '亲密';
        return '挚友';
    }

    async simulateTime(mode) {
        const btn = mode === 'next_day' 
            ? document.getElementById('simulate-day')
            : document.getElementById('simulate-schedule');
        
        btn.disabled = true;
        btn.textContent = '模拟中...';

        try {
            const response = await API.simulateTime(this.sessionId, mode);
            
            if (response.proactive_message) {
                this.addMessage({
                    role: 'assistant',
                    content: response.proactive_message.content,
                    is_proactive: true,
                    created_at: new Date().toISOString()
                });
            } else {
                this.showNotification('宠物这会儿没有回应。');
            }

            if (response.pet_status === 'hiding') {
                document.getElementById('pet-status').textContent = '躲起来了';
                document.getElementById('pet-status').className = 'pet-status hiding';
            } else {
                document.getElementById('pet-status').textContent = '在线陪伴';
                document.getElementById('pet-status').className = 'pet-status normal';
            }
            this.loadPetStatus();

        } catch (error) {
            alert('模拟失败: ' + error.message);
        } finally {
            btn.disabled = false;
            btn.textContent = mode === 'next_day' ? '推进到隔天' : '触发一次日程提醒';
        }
    }

    showLoading(show) {
        const loading = document.getElementById('loading-indicator');
        loading.style.display = show ? 'flex' : 'none';
    }

    async loadPetStatus() {
        if (!this.sessionId || !window.API?.getPetStatus) return;
        try {
            const data = await API.getPetStatus(this.sessionId);
            const status = data.status || 'idle';
            const label = data.status_label || '待机陪伴';
            const reason = data.status_reason || '随时等你来聊天';

            const statusEl = document.getElementById('pet-status');
            if (statusEl) {
                statusEl.textContent = label;
                statusEl.className = `pet-status normal status-${status}`;
            }

            const avatarEl = document.getElementById('pet-emoji');
            if (avatarEl) {
                avatarEl.classList.remove('status-idle', 'status-happy', 'status-lonely', 'status-sleepy', 'status-studying');
                avatarEl.classList.add(`status-${status}`);
            }

            const labelEl = document.getElementById('pet-state-label');
            const reasonEl = document.getElementById('pet-state-reason');
            const dotEl = document.getElementById('pet-state-dot');
            const moodEl = document.getElementById('pet-state-mood');
            if (labelEl) labelEl.textContent = label;
            if (reasonEl) reasonEl.textContent = reason;
            if (dotEl) dotEl.textContent = this.getStatusIcon(status);
            if (moodEl) {
                moodEl.textContent = data.mood_tendency
                    ? `近期倾向：${data.mood_tendency}`
                    : '情绪趋势会在多轮互动后自动沉淀。';
            }

            const setText = (id, value) => {
                const el = document.getElementById(id);
                if (el) el.textContent = value;
            };
            setText('today-interactions', data.today_interactions ?? 0);
            setText('companion-minutes', data.companion_minutes_today ?? 0);
            setText('consecutive-days', data.consecutive_days ?? 0);
            setText('growth-intimacy-level', data.intimacy_level || this.getIntimacyLevel(this.intimacy));
        } catch (error) {
            console.warn('加载宠物状态失败:', error);
        }
    }

    getStatusIcon(status) {
        const icons = {
            idle: '🐾',
            happy: '✨',
            lonely: '💭',
            sleepy: '🌙',
            studying: '📚'
        };
        return icons[status] || '🐾';
    }

    syncIntimacyRing(intimacy) {
        const ring = document.getElementById('intimacy-ring');
        if (!ring) return;

        const radius = 45;
        const circumference = 2 * Math.PI * radius;
        const safeValue = Math.max(0, Math.min(100, intimacy));
        const offset = circumference - (safeValue / 100) * circumference;

        ring.style.strokeDasharray = `${circumference}`;
        ring.style.strokeDashoffset = `${offset}`;
    }

    autoResizeTextarea(input) {
        if (!input) return;
        input.style.height = 'auto';
        input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
    }

    hexToRgba(hex, alpha) {
        const normalized = hex.replace('#', '');
        if (normalized.length !== 6) {
            return `rgba(238, 108, 77, ${alpha})`;
        }

        const r = parseInt(normalized.slice(0, 2), 16);
        const g = parseInt(normalized.slice(2, 4), 16);
        const b = parseInt(normalized.slice(4, 6), 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }

    showNotification(message) {
        const notification = document.createElement('div');
        notification.className = 'notification';
        notification.textContent = message;
        document.body.appendChild(notification);
        
        setTimeout(() => {
            notification.remove();
        }, 3000);
    }

    async toggleMemoryPanel() {
        const panel = document.getElementById('memory-panel');
        if (panel.style.display === 'none') {
            panel.style.display = 'block';
            this.loadMemoryPanel();
        } else {
            panel.style.display = 'none';
        }
    }

    async loadMemoryPanel() {
        try {
            const data = await API.getMemoryPanel(this.sessionId);
            document.getElementById('panel-intimacy').textContent = data.intimacy;
            document.getElementById('panel-intimacy-level').textContent = data.intimacy_level;
            document.getElementById('panel-total-chats').textContent = data.total_chats;
            
            // 加载用户画像，确保空值/null显示为"未知"
            const profile = data.user_profile || {};
            
            // 处理 interests 可能是数组的情况
            const formatProfileValue = (value) => {
                if (!value || value === '') return '未知';
                if (Array.isArray(value)) return value.join('、');
                return value;
            };
            
            const profileFields = ['region', 'identity', 'interests', 'occupation', 'personality_hint', 'active_hours', 'mood_tendency', 'extra_info'];
            profileFields.forEach(field => {
                const el = document.getElementById(`profile-${field}`);
                if (el) {
                    el.textContent = formatProfileValue(profile[field]);
                }
            });
        } catch (error) {
            console.error('加载记忆面板失败:', error);
        }
    }

    editProfile(field) {
        const valueEl = document.getElementById(`profile-${field}`);
        const actionsEl = document.getElementById(`actions-${field}`);
        const currentValue = valueEl.textContent;
        
        const fieldLabels = {
            'region': '地区',
            'identity': '身份',
            'interests': '兴趣',
            'occupation': '职业',
            'personality_hint': '性格',
            'active_hours': '活跃时段',
            'mood_tendency': '情绪倾向',
            'extra_info': '其他'
        };
        
        // 保存原始值用于取消
        valueEl.dataset.original = currentValue;
        
        // 替换显示值为输入框
        valueEl.innerHTML = `<input type="text" class="profile-inline-input" id="input-${field}" value="${currentValue === '未知' ? '' : currentValue}">`;
        
        // 替换编辑按钮为保存/取消按钮
        actionsEl.innerHTML = `
            <button class="save-btn" onclick="chatApp.saveProfile('${field}')">✓</button>
            <button class="cancel-btn" onclick="chatApp.cancelEdit('${field}')">✕</button>
        `;
        
        // 自动聚焦输入框
        const input = document.getElementById(`input-${field}`);
        input.focus();
        input.select();
    }
    
    cancelEdit(field) {
        const valueEl = document.getElementById(`profile-${field}`);
        const actionsEl = document.getElementById(`actions-${field}`);
        
        // 恢复原始值
        valueEl.textContent = valueEl.dataset.original || '未知';
        
        // 恢复编辑按钮
        actionsEl.innerHTML = `<button class="edit-btn" onclick="chatApp.editProfile('${field}')">✏️</button>`;
    }

    async saveProfile(field) {
        const input = document.getElementById(`input-${field}`);
        const value = input.value.trim();
        
        // 空内容保存为"未知"
        const finalValue = value || '未知';
        
        const valueEl = document.getElementById(`profile-${field}`);
        const actionsEl = document.getElementById(`actions-${field}`);
        
        try {
            // 收集所有画像字段
            const profileFields = ['region', 'identity', 'interests', 'occupation', 'personality_hint', 'active_hours', 'mood_tendency', 'extra_info'];
            const currentProfile = {};
            profileFields.forEach(f => {
                const el = document.getElementById(`profile-${f}`);
                if (el) {
                    currentProfile[f] = el.textContent;
                }
            });
            
            // 更新当前编辑字段的值
            currentProfile[field] = finalValue;
            
            console.log('保存用户画像:', currentProfile);
            
            await API.updateUserProfile(this.sessionId, currentProfile);
            
            // 更新显示值
            valueEl.textContent = finalValue;
            delete valueEl.dataset.original;
            
            // 恢复编辑按钮
            actionsEl.innerHTML = `<button class="edit-btn" onclick="chatApp.editProfile('${field}')">✏️</button>`;
            
            this.showNotification('✓ 用户画像已保存');
            
            // 重新加载记忆面板确保数据同步
            await this.loadMemoryPanel();
        } catch (error) {
            console.error('保存用户画像失败:', error);
            this.showNotification('保存失败，请重试');
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    async initVisitFeature() {
        const btn = document.getElementById('invite-visit-btn');
        if (!btn) return;

        try {
            const data = await API.listCustomPets();
            const allCustomPets = data.pets || [];
            const hostCustomPetId = localStorage.getItem('qagent_custom_pet_id');
            const otherCustomPets = allCustomPets.filter(p => p.pet_id !== hostCustomPetId);

            if (otherCustomPets.length >= 1 || allCustomPets.length >= 1) {
                btn.style.display = 'block';
                btn.addEventListener('click', () => this.openVisitModal(allCustomPets));
            }
        } catch (e) {
            console.warn('visit feature init failed:', e);
        }
    }

    async openVisitModal(allCustomPets) {
        const modal = document.getElementById('visit-guest-modal');
        const list = document.getElementById('visit-guest-list');
        const startBtn = document.getElementById('visit-start-btn');
        const cancelBtn = document.getElementById('visit-cancel-btn');

        const hostCustomPetId = localStorage.getItem('qagent_custom_pet_id');

        const guests = [];
        const otherCustomPets = allCustomPets.filter(p => p.pet_id !== hostCustomPetId);
        otherCustomPets.forEach(p => {
            guests.push({ id: p.pet_id, name: p.pet_name, isPreset: false });
        });

        const presetGuests = [
            { id: 'hot_dog', name: 'Hot Dog' },
            { id: 'cold_cat', name: 'Cold Cat' },
            { id: 'mouse', name: '鼠鼠' }
        ];
        presetGuests.forEach(p => guests.push({ ...p, isPreset: true }));

        list.innerHTML = '';
        let selectedGuestId = null;

        if (guests.length === 0) {
            list.innerHTML = '<p style="color:#888;font-size:13px;padding:8px;">没有可串门的宠物</p>';
        }

        guests.forEach(g => {
            const item = document.createElement('div');
            item.className = 'visit-guest-item';
            item.dataset.guestId = g.id;
            item.textContent = g.name + (g.isPreset ? ' (预置)' : '');
            item.addEventListener('click', () => {
                list.querySelectorAll('.visit-guest-item').forEach(el => el.classList.remove('selected'));
                item.classList.add('selected');
                selectedGuestId = g.id;
            });
            list.appendChild(item);
        });

        modal.style.display = 'flex';

        startBtn.onclick = async () => {
            if (!selectedGuestId) {
                alert('请先选择一只宠物');
                return;
            }
            const topic = document.getElementById('visit-topic-input').value.trim() || null;
            modal.style.display = 'none';
            await this.startVisit(selectedGuestId, topic);
        };

        cancelBtn.onclick = () => {
            modal.style.display = 'none';
        };
    }

    async startVisit(guestPetId, topic) {
        this.visitIsLoading = true;
        const panel = document.getElementById('visit-panel');
        const messagesDiv = document.getElementById('visit-messages');
        messagesDiv.innerHTML = '';
        panel.style.display = 'flex';

        try {
            const data = await API.startVisit(this.sessionId, guestPetId, topic);
            this.currentVisitId = data.visit_id;
            this.visitHostName = data.host_pet_name;
            this.visitGuestName = data.guest_pet_name;

            document.getElementById('visit-host-name').textContent = data.host_pet_name;
            document.getElementById('visit-guest-name').textContent = data.guest_pet_name;
            document.getElementById('visit-host-avatar').textContent = this.getPetEmoji(this.petType === 'custom' ? this._getRawPetType() : this.petType);
            document.getElementById('visit-guest-avatar').textContent = '🐾';
            document.getElementById('visit-topic-display').textContent = topic ? `话题: ${topic}` : '随便聊聊';

            this.addVisitBubble(data.opening_message.speaker, data.opening_message.content, 'host');
            this.bindVisitControls();

        } catch (e) {
            panel.style.display = 'none';
            alert('发起串门失败: ' + e.message);
        } finally {
            this.visitIsLoading = false;
        }
    }

    _getRawPetType() {
        try {
            const stored = localStorage.getItem('qagent_custom_pet');
            return stored ? JSON.parse(stored).pet_type : '';
        } catch (e) {
            return '';
        }
    }

    addVisitBubble(speakerName, content, side) {
        const messagesDiv = document.getElementById('visit-messages');
        const bubble = document.createElement('div');
        bubble.className = `visit-bubble ${side === 'host' ? 'host-bubble' : 'guest-bubble'}`;
        bubble.innerHTML = `<div class="visit-bubble-name">${this.escapeHtml(speakerName)}</div><p>${this.escapeHtml(content)}</p>`;
        messagesDiv.appendChild(bubble);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }

    bindVisitControls() {
        const nextBtn = document.getElementById('visit-next-btn');
        const endBtn = document.getElementById('visit-end-btn');

        nextBtn.onclick = null;
        endBtn.onclick = null;

        nextBtn.onclick = () => this.runAutoVisitTurns(6);
        endBtn.onclick = () => this.endVisit();
    }

    async runAutoVisitTurns(maxTurns) {
        const nextBtn = document.getElementById('visit-next-btn');
        const endBtn = document.getElementById('visit-end-btn');
        const loadingEl = document.getElementById('visit-loading');
        const interjectionInput = document.getElementById('visit-interjection-input');

        nextBtn.disabled = true;
        this.visitIsLoading = true;
        this._visitAborted = false;

        endBtn.onclick = () => { this._visitAborted = true; this.endVisit(); };

        let guestTurn = true;

        for (let i = 0; i < maxTurns; i++) {
            if (!this.currentVisitId || this._visitAborted) break;

            const interjection = (i === 0 && interjectionInput.value.trim()) ? interjectionInput.value.trim() : '';
            if (i === 0) interjectionInput.value = '';

            loadingEl.style.display = 'flex';

            try {
                const speaker = guestTurn ? 'guest' : 'host';
                const data = await API.nextVisitTurn(this.currentVisitId, interjection, speaker);
                loadingEl.style.display = 'none';

                if (data.message) {
                    const side = data.message.speaker === this.visitHostName ? 'host' : 'guest';
                    this.addVisitBubble(data.message.speaker, data.message.content, side);
                }

                if (data.visit_status !== 'active') break;
                guestTurn = !guestTurn;

                await new Promise(r => setTimeout(r, 800));
            } catch (e) {
                loadingEl.style.display = 'none';
                if (e.message && e.message.includes('limit reached')) {
                    this.showNotification('串门消息已达上限');
                    break;
                }
                console.error('visit turn error:', e);
                break;
            }
        }

        loadingEl.style.display = 'none';
        this.visitIsLoading = false;
        this._visitAborted = false;
        nextBtn.disabled = false;
        this.bindVisitControls();
    }

    async endVisit() {
        if (!this.currentVisitId) {
            document.getElementById('visit-panel').style.display = 'none';
            return;
        }

        try {
            await API.endVisit(this.currentVisitId, true);
            this.showNotification('串门已结束，对话亮点已写入记忆');
        } catch (e) {
            console.warn('end visit error:', e);
        } finally {
            this.currentVisitId = null;
            document.getElementById('visit-panel').style.display = 'none';
        }
    }
}

window.addEventListener('DOMContentLoaded', () => {
    window.chatApp = new ChatApp();
});
