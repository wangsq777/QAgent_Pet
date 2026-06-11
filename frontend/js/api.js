const API_BASE = '/api';

const API = {
    async createSession(userId, petType, customPetId = null) {
        const body = {
            user_id: userId,
            pet_type: petType
        };
        if (customPetId) {
            body.custom_pet_id = customPetId;
        }
        const response = await fetch(`${API_BASE}/sessions`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(body)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '创建会话失败');
        }

        return await response.json();
    },

    async chat(sessionId, content) {
        const response = await fetch(`${API_BASE}/sessions/${sessionId}/chat`, {
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
        const response = await fetch(`${API_BASE}/sessions/${sessionId}/messages`);
        
        if (!response.ok) {
            throw new Error('获取消息失败');
        }

        return await response.json();
    },

    async getSession(sessionId) {
        const response = await fetch(`${API_BASE}/sessions/${sessionId}`);
        
        if (!response.ok) {
            throw new Error('获取会话失败');
        }

        return await response.json();
    },

    async simulateTime(sessionId, mode) {
        const response = await fetch(`${API_BASE}/sessions/${sessionId}/simulate-time`, {
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
        const response = await fetch(`${API_BASE}/sessions/${sessionId}/memory`);
        
        if (!response.ok) {
            throw new Error('获取记忆面板失败');
        }

        return await response.json();
    },

    async updateUserProfile(sessionId, profileData) {
        const response = await fetch(`${API_BASE}/sessions/${sessionId}/profile`, {
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
    },

    // 自定义宠物API
    async createCustomPet(petData) {
        const response = await fetch(`${API_BASE}/custom-pets`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                pet_name: petData.pet_name,
                pet_type: petData.pet_type,
                personality_tags: petData.personality_tags,
                catchphrase: petData.catchphrase,
                special_habits: petData.special_habits,
                avatar_url: petData.avatar_url || null
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '创建自定义宠物失败');
        }

        return await response.json();
    },

    async getCustomPetTemplates() {
        const response = await fetch(`${API_BASE}/custom-pets/templates`);

        if (!response.ok) {
            throw new Error('获取宠物模板失败');
        }

        return await response.json();
    },

    async listCustomPets() {
        const response = await fetch(`${API_BASE}/custom-pets`);

        if (!response.ok) {
            throw new Error('获取自定义宠物列表失败');
        }

        return await response.json();
    },

    async deleteCustomPet(petId) {
        const response = await fetch(`${API_BASE}/custom-pets/detail/${petId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '删除失败');
        }

        return await response.json();
    }
};

window.API = API;