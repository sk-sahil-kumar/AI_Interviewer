import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import axios from 'axios';

const API_URL = `${import.meta.env.VITE_API_URL}/sessions/`;

const api = axios.create({
    baseURL: API_URL
});

api.interceptors.request.use((request) => {
    const user = JSON.parse(localStorage.getItem('user'));

    if (user && user.token) {
        request.headers.Authorization = `Bearer ${user.token}`;
    }

    return request;
});

api.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response?.status === 401) {
            localStorage.removeItem('user');
            window.location.href = '/login';
        }

        return Promise.reject(error);
    }
);

const getErrorMessage = (error) => {
    return (
        error.response?.data?.message ||
        error.message ||
        error.toString()
    );
};

const initialState = {
    sessions: [],
    activeSession: null,
    isGenerating: false,
    isError: false,
    isLoading: false,
    message: ''
};

// Get all sessions
export const getSessions = createAsyncThunk(
    'sessions/getAll',
    async (_, thunkAPI) => {
        try {
            const response = await api.get('/');
            return response.data;
        } catch (error) {
            return thunkAPI.rejectWithValue(getErrorMessage(error));
        }
    }
);

// Create session
export const createSession = createAsyncThunk(
    'sessions/create',
    async (sessionData, thunkAPI) => {
        try {
            const response = await api.post('/', sessionData);
            return response.data;
        } catch (error) {
            return thunkAPI.rejectWithValue(getErrorMessage(error));
        }
    }
);

// Get session by ID
export const getSessionById = createAsyncThunk(
    'sessions/getOne',
    async (sessionId, thunkAPI) => {
        try {
            const response = await api.get(`/${sessionId}`);
            return response.data;
        } catch (error) {
            return thunkAPI.rejectWithValue(getErrorMessage(error));
        }
    }
);

// Delete session
export const deleteSession = createAsyncThunk(
    'sessions/delete',
    async (sessionId, thunkAPI) => {
        try {
            const response = await api.delete(`/${sessionId}`);
            return response.data.id;
        } catch (error) {
            return thunkAPI.rejectWithValue(getErrorMessage(error));
        }
    }
);

// Submit answer
export const submitAnswer = createAsyncThunk(
    'sessions/submitAnswer',
    async ({ sessionId, formData }, thunkAPI) => {
        try {
            const response = await api.post(
                `/${sessionId}/submit-answer`,
                formData
            );

            return response.data;
        } catch (error) {
            return thunkAPI.rejectWithValue(getErrorMessage(error));
        }
    }
);

// End session
export const endSession = createAsyncThunk(
    'sessions/endSession',
    async (sessionId, thunkAPI) => {
        try {
            const response = await api.post(`/${sessionId}/end`);
            return response.data;
        } catch (error) {
            return thunkAPI.rejectWithValue(getErrorMessage(error));
        }
    }
);

export const sessionSlice = createSlice({
    name: 'sessions',
    initialState,

    reducers: {
        reset: (state) => {
            state.isError = false;
            state.message = '';
            state.isLoading = false;
            state.isGenerating = false;
        },

        socketUpdateSession: (state, action) => {
            const { sessionId, status, message, session } = action.payload;

            state.message = message || '';

            if (
                status === 'QUESTIONS_READY' ||
                status === 'GENERATION_FAILED'
            ) {
                state.isGenerating = false;
            }

            // Update active session
            if (
                session &&
                state.activeSession &&
                state.activeSession._id === sessionId
            ) {
                state.activeSession = {
                    ...state.activeSession,
                    ...session
                };
            }

            // Update session in history
            if (session) {
                state.sessions = state.sessions.map((item) =>
                    item._id === sessionId
                        ? { ...item, ...session }
                        : item
                );
            }
        },

        setActiveSession: (state, action) => {
            state.activeSession = action.payload;
        }
    },

    extraReducers: (builder) => {
        builder

            // Get all sessions
            .addCase(getSessions.pending, (state) => {
                state.isLoading = true;
            })
            .addCase(getSessions.fulfilled, (state, action) => {
                state.isLoading = false;
                state.sessions = action.payload;
            })
            .addCase(getSessions.rejected, (state, action) => {
                state.isLoading = false;
                state.isError = true;
                state.message = action.payload;
            })

            // Create session
            .addCase(createSession.pending, (state) => {
                state.isLoading = true;
                state.isGenerating = true;
                state.isError = false;
                state.message = '';
                state.activeSession = null;
            })
            .addCase(createSession.fulfilled, (state) => {
                state.isLoading = false;

                // API has accepted the session creation request.
                // AI generation continues in the backend.
                state.isGenerating = false;
            })
            .addCase(createSession.rejected, (state, action) => {
                state.isLoading = false;
                state.isGenerating = false;
                state.isError = true;
                state.message = action.payload || 'Session creation failed';
            })

            // Get one session
            .addCase(getSessionById.pending, (state) => {
                state.isLoading = true;
            })
            .addCase(getSessionById.fulfilled, (state, action) => {
                state.isLoading = false;
                state.activeSession = action.payload;
            })
            .addCase(getSessionById.rejected, (state, action) => {
                state.isLoading = false;
                state.isError = true;
                state.message = action.payload;
            })

            // Delete session
            .addCase(deleteSession.pending, (state) => {
                state.isLoading = true;
            })
            .addCase(deleteSession.fulfilled, (state, action) => {
                state.isLoading = false;

                state.sessions = state.sessions.filter(
                    (session) => session._id !== action.payload
                );
            })
            .addCase(deleteSession.rejected, (state, action) => {
                state.isLoading = false;
                state.isError = true;
                state.message = action.payload;
            })

            // Submit answer
            .addCase(submitAnswer.fulfilled, (state, action) => {
                if (
                    action.payload &&
                    Array.isArray(action.payload.questions)
                ) {
                    state.activeSession = action.payload;
                }
            })
            .addCase(submitAnswer.rejected, (state, action) => {
                state.isError = true;
                state.message = action.payload;
            })

            // End session
            .addCase(endSession.fulfilled, (state, action) => {
                if (action.payload) {
                    state.activeSession = action.payload;
                }
            })
            .addCase(endSession.rejected, (state, action) => {
                state.isError = true;
                state.message = action.payload;
            });
    }
});

export const {
    reset,
    socketUpdateSession,
    setActiveSession
} = sessionSlice.actions;

export default sessionSlice.reducer;