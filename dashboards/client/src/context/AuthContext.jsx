import { createContext, useContext, useEffect, useState } from "react";
import { clearToken, fetchMe, getToken, loginWithDemoCode, setToken } from "../services/auth";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [token, setTokenState] = useState(getToken());
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [bootstrapped, setBootstrapped] = useState(false);

  useEffect(() => {
    const url = new URL(window.location.href);
    const queryParams = new URLSearchParams(url.search);
    const hashParams = new URLSearchParams(url.hash.replace(/^#/, ""));
    const tokenFromUrl = queryParams.get("token") || hashParams.get("token");
    const errorFromUrl = queryParams.get("error") || hashParams.get("error");

    if (tokenFromUrl) {
      setToken(tokenFromUrl);
      setTokenState(tokenFromUrl);
      setError(null);
    } else if (errorFromUrl) {
      setError(errorFromUrl.replace(/_/g, " "));
    }

    if (tokenFromUrl || errorFromUrl) {
      url.search = "";
      url.hash = "";
      window.history.replaceState({}, document.title, url.toString());
    }
    setBootstrapped(true);
  }, []);

  useEffect(() => {
    if (!bootstrapped) return;
    const init = async () => {
      if (!token) {
        setLoading(false);
        return;
      }
      try {
        const res = await fetchMe(token);
        setUser(res.user);
        setError(null);
      } catch (err) {
        setError("Login expired. Please sign in again.");
        clearToken();
        setUser(null);
        setTokenState(null);
      } finally {
        setLoading(false);
      }
    };
    init();
  }, [token, bootstrapped]);

  const logout = () => {
    clearToken();
    setTokenState(null);
    setUser(null);
    setError(null);
    window.location.assign(`/login?ts=${Date.now()}`);
  };

  const demoLogin = async (code) => {
    try {
      setError(null);
      const res = await loginWithDemoCode(code);
      if (res?.token) {
        setToken(res.token);
        setTokenState(res.token);
      }
      return res;
    } catch (err) {
      throw err;
    }
  };

  const refreshUser = async () => {
    if (!token) {
      return null;
    }
    const res = await fetchMe(token);
    setUser(res.user);
    return res.user;
  };

  return (
    <AuthContext.Provider
      value={{
        token,
        user,
        loading,
        bootstrapped,
        error,
        logout,
        demoLogin,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
