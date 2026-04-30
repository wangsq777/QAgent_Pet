class ChatApp {
    constructor() {
        this.sessionId = localStorage.getItem('qagent_session_id');
        this.petType = localStorage.getItem('qagent_pet_type');
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

        this.renderPetInfo();
        this.loadHistoryMessages();
        this.bindEvents();
    }

    renderPetInfo() {
        const petNames = {
            'hot_dog': 'Hot Dog',
            'cold_cat': 'Cold Cat',
            'mouse': '鼠鼠'
        };
        const petImages = {
            'hot_dog': 'images/hot_dog.png',
            'cold_cat': 'images/cold_cat.png',
            'mouse': 'images/mouse.png'
        };
        const petColors = {
            'hot_dog': '#ff6b6b',
            'cold_cat': '#74b9ff',
            'mouse': '#fdcb6e'
        };

        const petName = petNames[this.petType] || 'Hot Dog';
        const petImage = petImages[this.petType] || 'images/hot_dog.png';
        
        // 设置宠物名称
        document.getElementById('pet-name').textContent = petName;
        
        // 设置宠物图片（替换 emoji）
        const petEmojiEl = document.getElementById('pet-emoji');
        petEmojiEl.innerHTML = `<img src="${petImage}" alt="${petName}" class="pet-avatar-img">`;
        
        document.getElementById('pet-color').style.background = petColors[this.petType] || '#ff6b6b';
        document.getElementById('pet-color').textContent = petName;
        document.getElementById('header-pet-name').textContent = petName;
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
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        document.getElementById('simulate-day').addEventListener('click', () => this.simulateTime('next_day'));
        document.getElementById('simulate-schedule').addEventListener('click', () => this.simulateTime('schedule_trigger'));

        document.getElementById('back-btn').addEventListener('click', () => {
            window.location.href = 'index.html';
        });

        document.getElementById('memory-panel-btn').addEventListener('click', () => this.toggleMemoryPanel());
    }

    addMessage(msg) {
        const msgDiv = document.createElement('div');
        const isUser = msg.role === 'user';
        msgDiv.className = `message ${isUser ? 'user-message' : 'pet-message'}`;

        const time = new Date(msg.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
        
        // 获取宠物图片路径
        const petImages = {
            'hot_dog': 'images/hot_dog.png',
            'cold_cat': 'images/cold_cat.png',
            'mouse': 'images/mouse.png'
        };
        const petImage = petImages[this.petType] || 'images/hot_dog.png';
        
        msgDiv.innerHTML = `
            ${!isUser ? `<div class="pet-avatar"><img src="${petImage}" alt="宠物" class="pet-avatar-img"></div>` : ''}
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
            if (response.daily_share) {
                this.addMessage({
                    role: 'assistant',
                    content: response.daily_share.content,
                    is_proactive: true,
                    created_at: new Date().toISOString()
                });
            }

            this.updateIntimacy(response.intimacy);
            this.updateTotalChats(response.total_chats);

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
                this.showNotification('🐱 Cold Cat 选择不回复...');
            }

            if (response.pet_status === 'hiding') {
                document.getElementById('pet-status').textContent = '躲藏中';
                document.getElementById('pet-status').className = 'pet-status hiding';
            } else {
                document.getElementById('pet-status').textContent = '正常';
                document.getElementById('pet-status').className = 'pet-status normal';
            }

        } catch (error) {
            alert('模拟失败: ' + error.message);
        } finally {
            btn.disabled = false;
            btn.textContent = mode === 'next_day' ? '模拟隔天' : '触发日程';
        }
    }

    showLoading(show) {
        const loading = document.getElementById('loading-indicator');
        loading.style.display = show ? 'flex' : 'none';
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
            const region = (!profile.region || profile.region === '') ? '未知' : profile.region;
            const identity = (!profile.identity || profile.identity === '') ? '未知' : profile.identity;
            const interests = (profile.interests && profile.interests.length > 0) 
                ? profile.interests.join('、') 
                : '未知';
            
            document.getElementById('profile-region').textContent = region;
            document.getElementById('profile-identity').textContent = identity;
            document.getElementById('profile-interests').textContent = interests;
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
            'interests': '兴趣'
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
            const currentProfile = {
                region: document.getElementById('profile-region').textContent,
                identity: document.getElementById('profile-identity').textContent,
                interests: document.getElementById('profile-interests').textContent,
                extra_info: null
            };
            
            if (field === 'region') currentProfile.region = finalValue;
            else if (field === 'identity') currentProfile.identity = finalValue;
            else if (field === 'interests') currentProfile.interests = finalValue;
            
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
}

window.addEventListener('DOMContentLoaded', () => {
    window.chatApp = new ChatApp();
});