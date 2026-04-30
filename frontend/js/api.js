const API_BASE = 'http://localhost:8080';

const API = {
    async createSession(userId, petType) {
        const response = await fetch(`${API_BASE}/api/sessions`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                user_id: userId,
                pet_type: petType
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '创建会话失败');
        }

        return await response.json();
    },

    async chat(sessionId, content) {
        const response = await fetch(`${API_BASE}/api/sessions/${sessionId}/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ content })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '发送消息失败');
        }

        return await response.json();
    },

    async getMessages(sessionId) {
        const response = await fetch(`${API_BASE}/api/sessions/${sessionId}/messages`);
        
        if (!response.ok) {
            throw new Error('获取消息失败');
        }

        return await response.json();
    },

    async getSession(sessionId) {
        const response = await fetch(`${API_BASE}/api/sessions/${sessionId}`);
        
        if (!response.ok) {
            throw new Error('获取会话失败');
        }

        return await response.json();
    },

    async simulateTime(sessionId, mode) {
        const response = await fetch(`${API_BASE}/api/sessions/${sessionId}/simulate-time`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ mode })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '模拟时间失败');
        }

        return await response.json();
    },

    async getMemoryPanel(sessionId) {
        const response = await fetch(`${API_BASE}/api/sessions/${sessionId}/memory`);
        
        if (!response.ok) {
            throw new Error('获取记忆面板失败');
        }

        return await response.json();
    },

    async updateUserProfile(sessionId, profileData) {
        const response = await fetch(`${API_BASE}/api/sessions/${sessionId}/profile`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(profileData)
        });

        if (!response.ok) {
            throw new Error('更新用户画像失败');
        }

        return await response.json();
    }
};

window.API = API;