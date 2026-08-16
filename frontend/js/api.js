const API_BASE = '/api';

/**
 * 获取当前用户 ID，自动从 localStorage 读取
 * 与 index.html / custom_pet.html 中生成的 user_id 保持一致
 */
function getUserId() {
    return localStorage.getItem('qagent_user_id') || 'anonymous';
}

/**
 * 构建带 X-User-Id 的公共请求头
 * @param {Object} extra - 额外请求头（如 Content-Type）
 * @returns {Object}
 */
function buildHeaders(extra = {}) {
    return {
        'X-User-Id': getUserId(),
        ...extra
    };
}

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
            headers: buildHeaders({ 'Content-Type': 'application/json' }),
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
            headers: buildHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ content })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '发送消息失败');
        }

        return await response.json();
    },

    async getMessages(sessionId) {
        const response = await fetch(`${API_BASE}/sessions/${sessionId}/messages`, {
            headers: buildHeaders()
        });

        if (!response.ok) {
            throw new Error('获取消息失败');
        }

        return await response.json();
    },

    async getSession(sessionId) {
        const response = await fetch(`${API_BASE}/sessions/${sessionId}`, {
            headers: buildHeaders()
        });

        if (!response.ok) {
            throw new Error('获取会话失败');
        }

        return await response.json();
    },

    async simulateTime(sessionId, mode) {
        const response = await fetch(`${API_BASE}/sessions/${sessionId}/simulate-time`, {
            method: 'POST',
            headers: buildHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ mode })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '模拟时间失败');
        }

        return await response.json();
    },

    async getMemoryPanel(sessionId) {
        const response = await fetch(`${API_BASE}/sessions/${sessionId}/memory`, {
            headers: buildHeaders()
        });

        if (!response.ok) {
            throw new Error('获取记忆面板失败');
        }

        return await response.json();
    },

    async getPetStatus(sessionId) {
        const response = await fetch(`${API_BASE}/sessions/${sessionId}/pet-status`, {
            headers: buildHeaders()
        });

        if (!response.ok) {
            throw new Error('获取宠物状态失败');
        }

        return await response.json();
    },

    async getProactiveSettings() {
        const response = await fetch(`${API_BASE}/proactive/settings`, { headers: buildHeaders() });
        if (!response.ok) throw new Error('获取主动陪伴设置失败');
        return await response.json();
    },

    async updateProactiveSettings(settings) {
        const response = await fetch(`${API_BASE}/proactive/settings`, {
            method: 'PUT', headers: buildHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify(settings)
        });
        if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || '更新主动陪伴设置失败');
        return await response.json();
    },

    async listSchedules(sessionId) {
        const response = await fetch(`${API_BASE}/sessions/${sessionId}/schedules`, { headers: buildHeaders() });
        if (!response.ok) throw new Error('获取日程失败');
        return await response.json();
    },

    async listConcerns(sessionId) {
        const response = await fetch(`${API_BASE}/sessions/${sessionId}/concerns`, { headers: buildHeaders() });
        if (!response.ok) throw new Error('获取惦记事项失败');
        return await response.json();
    },

    async confirmConcern(sessionId, concernId) {
        const response = await fetch(`${API_BASE}/sessions/${sessionId}/concerns/${concernId}/confirm`, { method: 'POST', headers: buildHeaders() });
        if (!response.ok) throw new Error('确认惦记事项失败');
        return await response.json();
    },

    async dismissConcern(sessionId, concernId) {
        const response = await fetch(`${API_BASE}/sessions/${sessionId}/concerns/${concernId}/dismiss`, { method: 'POST', headers: buildHeaders() });
        if (!response.ok) throw new Error('拒绝惦记事项失败');
        return await response.json();
    },

    async leisureModules() {
        const response = await fetch(`${API_BASE}/leisure/modules`, { headers: buildHeaders() });
        if (!response.ok) throw new Error('获取摸鱼模块失败');
        return await response.json();
    },

    async openLeisureSession(moduleId, contentRefId = null) {
        const response = await fetch(`${API_BASE}/leisure/sessions`, {
            method: 'POST',
            headers: buildHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ module_id: moduleId, content_ref_id: contentRefId })
        });
        if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || '打开摸鱼会话失败');
        return await response.json();
    },

    async closeLeisureSession(sessionId, reason = 'user_exit') {
        const response = await fetch(`${API_BASE}/leisure/sessions/${sessionId}/close?reason=${encodeURIComponent(reason)}`, {
            method: 'POST', headers: buildHeaders()
        });
        if (!response.ok) throw new Error('结束摸鱼会话失败');
        return await response.json();
    },

    async listLeisureNovels() {
        const response = await fetch(`${API_BASE}/leisure/novels`, { headers: buildHeaders() });
        if (!response.ok) throw new Error('获取小说书架失败');
        return await response.json();
    },

    async listNovelChapters(bookId) {
        const response = await fetch(`${API_BASE}/leisure/novels/${encodeURIComponent(bookId)}/chapters`, { headers: buildHeaders() });
        if (!response.ok) throw new Error('获取章节失败');
        return await response.json();
    },

    async getNovelChapter(bookId, chapterId) {
        const response = await fetch(`${API_BASE}/leisure/novels/${encodeURIComponent(bookId)}/chapters/${encodeURIComponent(chapterId)}`, { headers: buildHeaders() });
        if (!response.ok) throw new Error('获取章节内容失败');
        return await response.json();
    },

    async getNovelProgress(bookId) {
        const response = await fetch(`${API_BASE}/leisure/novels/${encodeURIComponent(bookId)}/progress`, { headers: buildHeaders() });
        if (!response.ok) throw new Error('获取阅读进度失败');
        return await response.json();
    },

    async saveNovelProgress(bookId, progress) {
        const response = await fetch(`${API_BASE}/leisure/novels/${encodeURIComponent(bookId)}/progress`, {
            method: 'PUT',
            headers: buildHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(progress)
        });
        if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || '保存阅读进度失败');
        return await response.json();
    },

    async updateUserProfile(sessionId, profileData) {
        const response = await fetch(`${API_BASE}/sessions/${sessionId}/profile`, {
            method: 'PUT',
            headers: buildHeaders({ 'Content-Type': 'application/json' }),
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
            headers: buildHeaders({ 'Content-Type': 'application/json' }),
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
        const response = await fetch(`${API_BASE}/custom-pets/templates`, {
            headers: buildHeaders()
        });

        if (!response.ok) {
            throw new Error('获取宠物模板失败');
        }

        return await response.json();
    },

    async listCustomPets() {
        const response = await fetch(`${API_BASE}/custom-pets`, {
            headers: buildHeaders()
        });

        if (!response.ok) {
            throw new Error('获取自定义宠物列表失败');
        }

        return await response.json();
    },

    async deleteCustomPet(petId) {
        const response = await fetch(`${API_BASE}/custom-pets/detail/${petId}`, {
            method: 'DELETE',
            headers: buildHeaders()
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '删除失败');
        }

        return await response.json();
    },

    async startVisit(hostSessionId, guestPetId, topic) {
        const response = await fetch(`${API_BASE}/visits`, {
            method: 'POST',
            headers: buildHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ host_session_id: hostSessionId, guest_pet_id: guestPetId, topic: topic || null })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '发起串门失败');
        }

        return await response.json();
    },

    async nextVisitTurn(visitId, userInterjection = "", nextSpeaker = "auto") {
        const response = await fetch(`${API_BASE}/visits/${visitId}/next`, {
            method: 'POST',
            headers: buildHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ user_interjection: userInterjection, next_speaker: nextSpeaker })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '获取下一回合失败');
        }

        return await response.json();
    },

    async endVisit(visitId, saveMemory = true) {
        const response = await fetch(`${API_BASE}/visits/${visitId}/end`, {
            method: 'POST',
            headers: buildHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ save_memory: saveMemory })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '结束串门失败');
        }

        return await response.json();
    },

    async listVisits() {
        const response = await fetch(`${API_BASE}/visits`, {
            headers: buildHeaders()
        });

        if (!response.ok) {
            throw new Error('获取串门记录失败');
        }

        return await response.json();
    },

    // ============ 陪我学（GitHub 开源项目教学）============
    async analyzeLearningRepo(petId, githubUrl) {
        const response = await fetch(`${API_BASE}/learning/analyze`, {
            method: 'POST',
            headers: buildHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ pet_id: petId, github_url: githubUrl })
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || '分析项目失败');
        }

        return await response.json();
    },

    async createLearningSession(petId, githubUrl, outline) {
        const response = await fetch(`${API_BASE}/learning/sessions`, {
            method: 'POST',
            headers: buildHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ pet_id: petId, github_url: githubUrl, outline })
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || '创建学习会话失败');
        }

        return await response.json();
    },

    async getLearningSession(sessionId) {
        const response = await fetch(`${API_BASE}/learning/sessions/${sessionId}`, {
            headers: buildHeaders()
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || '获取学习会话失败');
        }

        return await response.json();
    },

    async teachLearningChapter(sessionId, chapterId) {
        const response = await fetch(`${API_BASE}/learning/sessions/${sessionId}/chapters/${chapterId}/teach`, {
            method: 'POST',
            headers: buildHeaders({ 'Content-Type': 'application/json' })
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || '生成章节讲解失败');
        }

        return await response.json();
    },

    async completeLearningChapter(sessionId, chapterId) {
        const response = await fetch(`${API_BASE}/learning/sessions/${sessionId}/chapters/${chapterId}/complete`, {
            method: 'POST',
            headers: buildHeaders({ 'Content-Type': 'application/json' })
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || '完成章节失败');
        }

        return await response.json();
    },

    async askLearningQuestion(sessionId, target, question, chapterId = null) {
        const response = await fetch(`${API_BASE}/learning/sessions/${sessionId}/ask`, {
            method: 'POST',
            headers: buildHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ target, question, chapter_id: chapterId })
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || '提问失败');
        }

        return await response.json();
    },

    async pauseLearningSession(sessionId) {
        const response = await fetch(`${API_BASE}/learning/sessions/${sessionId}/pause`, {
            method: 'POST',
            headers: buildHeaders({ 'Content-Type': 'application/json' })
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || '暂停学习失败');
        }

        return await response.json();
    },

    async completeLearningSession(sessionId) {
        const response = await fetch(`${API_BASE}/learning/sessions/${sessionId}/complete`, {
            method: 'POST',
            headers: buildHeaders({ 'Content-Type': 'application/json' })
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || '完成学习失败');
        }

        return await response.json();
    }
};

window.API = API;
