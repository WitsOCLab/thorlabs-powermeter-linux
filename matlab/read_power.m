% Ten averaged readings from a Thorlabs power meter, from MATLAB, through the thorlabs_pm Python package.
% Needs MATLAB R2022a or newer and a Python with `pip install thorlabs-powermeter-linux`.
pyenv(Version="/usr/bin/python3");                      % the Python that has the package
pm = py.thorlabs_pm.PowerMeter(pyargs('wavelength_nm', 532));
for k = 1:10
    r = pm.read(int32(5));
    fprintf('%s  %.4e W  +/- %.1e\n', datestr(now, 'HH:MM:SS'), double(r{'watts'}), double(r{'std_watts'}));
    pause(0.2);
end
pm.close();
