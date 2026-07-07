const argValue = (prefix) => {
  const found = process.argv.find((arg) => arg.startsWith(prefix));
  return found ? decodeURIComponent(found.slice(prefix.length)) : '';
};

const userId = argValue('--qagent-user-id=');
const sessionId = argValue('--qagent-session-id=');
const petType = argValue('--qagent-pet-type=');
const customPetId = argValue('--qagent-custom-pet-id=');

if (userId) localStorage.setItem('qagent_user_id', userId);
if (sessionId) localStorage.setItem('qagent_session_id', sessionId);
if (petType) localStorage.setItem('qagent_pet_type', petType);
if (customPetId) localStorage.setItem('qagent_custom_pet_id', customPetId);
