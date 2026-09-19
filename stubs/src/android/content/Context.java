package android.content;

public abstract class Context {
    public static final String BLUETOOTH_SERVICE = "bluetooth";
    public abstract Object getSystemService(String name);
}
